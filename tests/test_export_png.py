# -*- coding: utf-8 -*-
"""test_export_png.py — PNG 导出器（export_png.py）的回归测试。

帧编解码为纯逻辑测试（必跑）；浏览器端到端导出在有本机 Chrome/Chromium/Edge 时
执行真实 1080×1440 导出（导出回归的硬证明），无浏览器环境自动跳过。
"""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_png as ep  # noqa: E402


class TestFrameCodec(unittest.TestCase):
    """WebSocket 客户端帧编码（客户端→服务端必须掩码）与长度分支。"""

    def test_small_frame_roundtrip_mask(self):
        mask = b"\x0f\x0e\x0d\x0c"
        payload = "hello 导出".encode("utf-8")
        frame = ep.encode_client_frame(payload, mask)
        # 第 1 字节：FIN+TEXT(0x81)；第 2 字节：MASK(0x80)+len
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 0x80 | len(payload))
        self.assertEqual(frame[2:6], mask)
        unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(frame[6:]))
        self.assertEqual(unmasked, payload)

    def test_medium_frame_uses_16bit_length(self):
        mask = b"\x01\x02\x03\x04"
        payload = b"x" * 300
        frame = ep.encode_client_frame(payload, mask)
        self.assertEqual(frame[1], 0x80 | 126)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 300)

    def test_large_frame_uses_64bit_length(self):
        mask = b"\x01\x02\x03\x04"
        payload = b"x" * 70000
        frame = ep.encode_client_frame(payload, mask)
        self.assertEqual(frame[1], 0x80 | 127)
        self.assertEqual(struct.unpack(">Q", frame[2:10])[0], 70000)

    def test_empty_payload_frame(self):
        mask = b"\x00\x00\x00\x00"
        frame = ep.encode_client_frame(b"", mask)
        self.assertEqual(frame[1], 0x80)
        self.assertEqual(len(frame), 6)


class TestBrowserEndToEnd(unittest.TestCase):
    """有浏览器时跑真实导出（1080×1440 卡片 + 整页报告）。"""

    def _browser(self):
        try:
            return ep.find_browser(None)
        except FileNotFoundError:
            return None

    def test_export_card_png_exact_dimensions(self):
        browser = self._browser()
        if browser is None:
            self.skipTest("本机无 Chrome/Chromium/Edge，浏览器端导出跳过（预览页按钮为等效入口）")
        card = ROOT / "dist/publish/case-a-freshgrad-ops/cards/card-01-cover.html"
        if not card.exists():
            self.skipTest("发布产物未生成（先跑 render_editorial.py）")
        import base64
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "card.png"
            ep.export_png(card, out, browser, 1080, 1440, fullpage=False)
            data = out.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG"), "导出必须是 PNG")
        # IHDR 宽高
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual((w, h), (1080, 1440), "卡片导出必须精确 1080×1440")


if __name__ == "__main__":
    unittest.main()
