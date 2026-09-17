#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_png.py — 发布资产 PNG 导出器（零第三方依赖）。

定位：
  * 与 cards-preview.html 的「导出 PNG」按钮共用同一排版实现（都渲染卡片 HTML 本体），
    批量 / 无人值守场景用本脚本驱动本机 Chrome（DevTools 协议，标准库实现）。
  * 卡片：固定 1080×1440 视口截图；报告：指定宽度整页长图（captureBeyondViewport）。
  * 本机需装有 Chrome / Chromium / Edge（Apple Silicon 原生支持）。浏览器是导出期
    工具，不是 skill 运行依赖——不装浏览器时预览页按钮同样是导出入口。

用法：
  python3 scripts/export_png.py --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --html dist/publish/case-a/cards/card-01-cover.html --out dist/publish/case-a/cards/card-01-cover.png
  python3 scripts/export_png.py ... --html report.html --out report.png --width 390 --fullpage
"""
import argparse
import base64
import json
import os
import random
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium-browser",
]


# ---------------------------------------------------------------------------
# 最小 WebSocket 客户端（客户端帧必须掩码；服务端帧不掩码）
# ---------------------------------------------------------------------------

class WSClient:
    def __init__(self, host: str, port: int, path: str, timeout: float = 30.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 握手失败：连接中断")
            resp += chunk
        head, _, rest = resp.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"WebSocket 握手被拒绝: {head[:200]!r}")
        self._buf = rest

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("连接中断")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_text(self, payload: str) -> None:
        data = payload.encode("utf-8")
        mask = random.getrandbits(32).to_bytes(4, "big")
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read_frame(self) -> tuple:
        head = self._recv_exact(2)
        opcode = head[0] & 0x0F
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._recv_exact(8))[0]
        payload = self._recv_exact(n) if n else b""
        return opcode, payload

    def recv_text(self) -> str:
        """收文本帧；自动回应 ping，忽略 pong/close 前的空等。"""
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x1:
                return payload.decode("utf-8", "replace")
            if opcode == 0x2:
                continue  # 二进制（本用例不会出现）
            if opcode == 0x9:  # ping → pong（客户端帧必须掩码）
                mask = random.getrandbits(32).to_bytes(4, "big")
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + masked)
                continue
            if opcode == 0x8:
                raise ConnectionError("服务端关闭连接")
            # continuation 等场景不出现于 CDP 单帧消息

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def encode_client_frame(data: bytes, mask: bytes) -> bytes:
    """单帧编码（测试用：与 send_text 同一口径）。"""
    header = bytearray([0x81])
    n = len(data)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    header += mask
    return bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


# ---------------------------------------------------------------------------
# CDP 会话
# ---------------------------------------------------------------------------

class CDPSession:
    _msg_id = 0

    def __init__(self, ws: WSClient):
        self.ws = ws

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        CDPSession._msg_id += 1
        mid = CDPSession._msg_id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} 失败: {msg['error']}")
                return msg.get("result", {})
            # 事件消息（Page.loadEventFired 等）继续等响应
        raise TimeoutError(f"CDP {method} 超时")

    def wait_event(self, name: str, timeout: float = 30.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv_text())
            if msg.get("method") == name:
                return msg.get("params", {})
        raise TimeoutError(f"等待事件 {name} 超时")


def find_browser(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for cand in CHROME_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("未找到 Chrome/Chromium/Edge；用 --browser 指定路径（导出需要本机浏览器）")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def export_png(html_path: Path, out_path: Path, browser: str, width: int, height: int,
               fullpage: bool, settle_ms: int = 450) -> None:
    url = html_path.resolve().as_uri()
    port = free_port()
    proc = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={port}", "--user-data-dir=" + str(
             Path(tempfile_dir()) / f"jdmatch-cdp-{port}"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws: Optional[WSClient] = None
    try:
        target_ws = None
        for _ in range(60):  # 等调试端口就绪
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
                    targets = json.loads(resp.read().decode())
                page = next((t for t in targets if t.get("type") == "page"), None)
                if page:
                    target_ws = page["webSocketDebuggerUrl"]
                    break
            except Exception:
                continue
        if not target_ws:
            raise RuntimeError("Chrome 调试端口未就绪")
        host = "127.0.0.1"
        path = target_ws.split(f"://{host}", 1)[1].split("/", 1)
        ws = WSClient(host, port, "/" + path[1] if len(path) > 1 else "/")
        cdp = CDPSession(ws)
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        cdp.call("Page.navigate", {"url": url})
        try:
            cdp.wait_event("Page.loadEventFired", timeout=20)
        except TimeoutError:
            pass  # 本地文件通常瞬时完成
        cdp.call("Runtime.evaluate",
                 {"expression": f"new Promise(r => setTimeout(r, {settle_ms}))", "awaitPromise": True,
                  "returnByValue": True})
        params: Dict[str, Any] = {"format": "png"}
        if fullpage:
            params["captureBeyondViewport"] = True
        result = cdp.call("Page.captureScreenshot", params, timeout=60)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(result["data"]))
    finally:
        if ws:
            ws.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def tempfile_dir() -> str:
    import tempfile
    return tempfile.gettempdir()


def main() -> int:
    ap = argparse.ArgumentParser(description="卡片/报告 PNG 导出（本机 Chrome，DevTools 协议）")
    ap.add_argument("--browser", default=None, help="Chrome/Chromium/Edge 可执行文件路径（默认自动探测）")
    ap.add_argument("--html", required=True, help="输入 HTML（卡片或报告）")
    ap.add_argument("--out", required=True, help="输出 PNG 路径")
    ap.add_argument("--width", type=int, default=1080, help="视口宽（卡片 1080 / 桌面报告 1440 / 手机 390）")
    ap.add_argument("--height", type=int, default=1440, help="视口高（卡片 1440；整页导出时会被内容高度覆盖）")
    ap.add_argument("--fullpage", action="store_true", help="整页长图（报告用；卡片固定尺寸无需开启）")
    args = ap.parse_args()

    html_path, out_path = Path(args.html), Path(args.out)
    if not html_path.exists():
        print(f"[错误] 输入不存在: {html_path}", file=sys.stderr)
        return 1
    try:
        browser = find_browser(args.browser)
        export_png(html_path, out_path, browser, args.width, args.height, args.fullpage)
    except Exception as exc:  # noqa: BLE001 —— CLI 汇总报错
        print(f"[错误] 导出失败: {exc}", file=sys.stderr)
        return 1
    size = out_path.stat().st_size
    print(f"[成功] {out_path} ({size} 字节, {args.width}×{'全页' if args.fullpage else args.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
