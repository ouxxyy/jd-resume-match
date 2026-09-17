#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_resume.py — T2 材料提取与来源定位（PDF / DOCX / 文本 / JD 链接）。

定位（重要）：
  * 纯标准库实现（Python 3.9+，零生产依赖），为 skill 初诊提供带来源定位的
    提取结果；来源编号（src-resume-N / src-jd-N）与定位符（行号 L / 段落 ¶ /
    页码 P）供分析阶段的逐字引用使用。
  * 能力边界是显式的，不做静默误读：零依赖 PDF 提取只可靠支持
    「文本型 PDF（简单字体 + Flate/无压缩内容流）」；CID/Type0 字体（中文 PDF
    常见）会触发明确告警而不是静默乱码。「乱码必有告警」由双防线保证
    （0.1.1，MYW-66）：防线一对压缩对象流（ObjStm）解压后执行与原始字节
    相同的 CID 字体特征扫描（解压失败降级防线二）；防线二对提取输出文本做
    CID 乱码特征兜底检测（任何成因，含 Chrome/Word/WPS 新式导出）。
    加密、损坏、扫描件（图片型）、空文件、链接失败一律进入明确的
    insufficient_input 路径并给出修复指引，不允许下游凭残缺结果强行评分。
  * 本脚本不读取、不存储、不请求任何模型密钥。

用法：
  python3 scripts/extract_resume.py --resume resume.pdf --jd-file jd.txt --jd-url https://... --output extraction.json

  --resume   简历文件，可重复（.pdf/.docx/.txt/.md）
  --jd-file  JD 文件，可重复（同上格式）
  --jd-url   JD 链接，可重复（http/https/file；失败进入降级路径）
  --output   输出 JSON 路径；缺省打印到 stdout

退出码：0 = 全部输入提取成功；1 = 存在信息不足输入（JSON 仍会产出，供展示降级指引）；
        2 = 用法/参数错误。
"""
import argparse
import html as html_mod
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EXTRACTION_VERSION = "jd-extract/0.1.1"
MAX_URL_BYTES = 2 * 1024 * 1024          # 链接内容上限 2MB
MAX_XML_BYTES = 64 * 1024 * 1024         # DOCX document.xml 解析上限
TEXT_OUTPUT_CHAR_CAP = 400_000           # 单输入输出文本上限（防异常巨型输出）
SPARSE_CHARS_PER_PAGE = 20               # PDF 平均每页可提取字符低于该值 → 疑似扫描件
USER_AGENT = "jd-resume-match-skill/0.1 (+local; stdlib-only)"
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# ---- 降级原因码 → 用户可执行的修复指引（写入输出，供 skill 原样转述）----
GUIDANCE = {
    "file_not_found": "找不到该文件。请确认路径与文件名（注意中文文件名与扩展名），或直接粘贴文本内容。",
    "empty_file": "文件为空或没有任何可提取文本。请确认导出了正确文件；或直接把简历/JD 内容以文本粘贴给我。",
    "undecodable_text": "文本文件编码无法识别（已尝试 UTF-8/GB18030）。请将文件另存为 UTF-8 编码，或直接粘贴文本。",
    "corrupt_pdf": "PDF 文件头缺失或内容流损坏，无法解析。请重新导出 PDF；若方便请直接粘贴文本版本。",
    "encrypted_pdf": "该 PDF 已加密，本工具不做解密。请提供未加密版本，或用文本粘贴内容。",
    "scanned_pdf_suspected": "该文件几乎没有可提取文字，疑似扫描件/图片型。本工具不做 OCR：请提供可复制文本的版本，或直接粘贴文本内容。",
    "corrupt_docx": "DOCX 文件损坏或缺少正文（word/document.xml）。请重新另存为 .docx；或直接粘贴文本。",
    "encrypted_or_legacy_doc": "该文件是旧版 .doc 二进制或已加密文档，本工具不支持。请用 Word/WPS 另存为 .docx，或直接粘贴文本。",
    "unsupported_format": "暂只支持 .pdf / .docx / .txt / .md 文件。请转换格式后重试，或直接粘贴文本。",
    "link_fetch_failed": "JD 链接读取失败（网络错误、需要登录或页面不可达）。请把 JD 全文直接粘贴给我。",
    "link_content_too_large": "JD 链接内容超过 2MB 上限。请把 JD 全文直接粘贴给我。",
    "link_not_readable": "链接返回的内容不是可读文本（可能是图片或二进制）。请把 JD 全文直接粘贴给我。",
}
WARNING_GUIDANCE = {
    "cid_font_limited_support": "该 PDF 使用 CID/Type0 字体（中文 PDF 常见），零依赖提取对这类字体支持有限，文字可能乱码或缺字。请人工核对提取摘要：若乱码，请改贴文本或改用 DOCX。",
    "page_order_approximate": "无法完整解析该 PDF 的页面树，页序为近似还原；引用定位请结合内容人工核对。",
    "stream_decompress_failed": "部分内容流解压失败，对应内容可能缺失，请人工核对提取摘要是否完整。",
    "html_content_stripped": "链接内容是网页，已剥离 HTML 标签提取正文；导航/广告等噪音可能混入，请人工核对 JD 全文是否完整。",
    "encoding_fallback": "文本不是 UTF-8，已按检测到的编码解码；如出现乱码请提供 UTF-8 版本。",
    "output_truncated": "提取文本超过输出上限，已截断；请人工核对是否缺失关键内容。",
}


# ================= 通用工具 =================

def _decode_bytes(data: bytes, prefer: Optional[str] = None) -> Tuple[str, List[str]]:
    """按 UTF-8 优先、GB18030 兜底解码；返回 (文本, 警告列表)。全部失败抛 UnicodeDecodeError。"""
    warnings: List[str] = []
    candidates: List[Optional[str]] = ([prefer] if prefer else []) + ["utf-8-sig", "utf-8", "gb18030"]
    seen = set()
    for enc in candidates:
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            text = data.decode(enc)
            if enc not in ("utf-8", "utf-8-sig"):
                warnings.append(f"encoding_fallback: 非 UTF-8 编码，已按 {enc} 解码")
            return text, warnings
        except (UnicodeDecodeError, LookupError):
            continue
    raise UnicodeDecodeError("utf-8", data[:32], 0, 1, "all candidate encodings failed")


def _cap_text(text: str, warnings: List[str]) -> str:
    if len(text) > TEXT_OUTPUT_CHAR_CAP:
        warnings.append(f"output_truncated: 文本超过 {TEXT_OUTPUT_CHAR_CAP} 字符上限，已截断")
        text = text[:TEXT_OUTPUT_CHAR_CAP]
    return text


def _split_line_blocks(text: str, locator_fmt: str) -> List[Dict[str, str]]:
    """按行产出定位块；locator_fmt 例如 'L{n}'。"""
    blocks: List[Dict[str, str]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            blocks.append({"locator": locator_fmt.format(n=n), "text": line})
    return blocks


# ================= PDF（有限支持 + 显式能力检测） =================

def _pdf_literal_string_decode(s: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in "nrtbf()\\":
                out.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(nxt, nxt))
                i += 2
            elif nxt.isdigit():
                j = i + 1
                oct_digits = ""
                while j < len(s) and s[j].isdigit() and len(oct_digits) < 3:
                    oct_digits += s[j]
                    j += 1
                try:
                    out.append(chr(int(oct_digits, 8)))
                except ValueError:
                    pass
                i = j
            elif nxt in ("\n", "\r"):
                i += 2
                if nxt == "\r" and i < len(s) and s[i] == "\n":
                    i += 1
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _pdf_content_to_text(data: bytes) -> str:
    """从页面内容流提取文本：处理 Tj / TJ / ' / " 与常见换位操作符。"""
    try:
        src = data.decode("latin-1")
    except Exception:
        return ""
    tokens: List[Tuple[str, Any]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "(":
            depth = 1
            j = i + 1
            buf: List[str] = []
            while j < n and depth > 0:
                ch = src[j]
                if ch == "\\":
                    buf.append(ch)
                    if j + 1 < n:
                        buf.append(src[j + 1])
                    j += 2
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                buf.append(ch)
                j += 1
            tokens.append(("str", _pdf_literal_string_decode("".join(buf))))
            i = j + 1
            continue
        if c == "<" and i + 1 < n and src[i + 1] != "<":
            j = src.find(">", i)
            if j == -1:
                break
            hexs = re.sub(r"\s+", "", src[i + 1:j])
            if len(hexs) % 2:
                hexs += "0"
            try:
                tokens.append(("str", bytes.fromhex(hexs).decode("latin-1")))
            except ValueError:
                pass
            i = j + 1
            continue
        if c == "<":
            i += 2
            continue
        if c == ">" and i + 1 < n and src[i + 1] == ">":
            i += 2
            continue
        if c in "[]":
            tokens.append(("bracket", c))
            i += 1
            continue
        if c == "/":
            m = re.match(r"/[^\s/\[\]<>(){}]*", src[i:])
            i += len(m.group(0)) if m else 1
            continue
        m = re.match(r"[-+]?\d*\.?\d+", src[i:])
        if m:
            try:
                tokens.append(("num", float(m.group(0))))
            except ValueError:
                pass
            i += len(m.group(0))
            continue
        m = re.match(r"[A-Za-z'\"*]+", src[i:])
        if m:
            tokens.append(("op", m.group(0)))
            i += len(m.group(0))
            continue
        i += 1

    out: List[str] = []
    operand: List[Any] = []
    for kind, val in tokens:
        if kind in ("str", "num", "bracket"):
            operand.append(val)
            continue
        op = val
        if op == "Tj":
            out.extend(v for v in operand if isinstance(v, str))
        elif op in ("'", '"'):
            out.extend(v for v in operand if isinstance(v, str))
            out.append("\n")
        elif op == "TJ":
            for v in operand:
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, float) and v <= -100:
                    out.append(" ")
        elif op in ("Td", "TD", "T*", "ET"):
            out.append("\n")
        operand.clear()
    lines = [ln.rstrip() for ln in "".join(out).split("\n")]
    return "\n".join(ln for ln in lines if ln.strip())


def _pdf_dict_backwards(raw: bytes, pos: int) -> Optional[Tuple[bytes, int]]:
    """找 raw[pos] 之前紧邻的 << >> 字典，返回 (字典字节, 起始下标)。"""
    end = raw.rfind(b">>", 0, pos)
    if end == -1:
        return None
    depth = 0
    i = end + 2
    while i >= 2:
        chunk = raw[i - 2:i]
        if chunk == b">>":
            depth += 1
            i -= 2
        elif chunk == b"<<":
            depth -= 1
            if depth == 0:
                return raw[i - 2:end + 2], i - 2
            i -= 2
        else:
            i -= 1
    return None


def _pdf_obj_num_before(raw: bytes, dict_start: int) -> Optional[int]:
    window = raw[max(0, dict_start - 96):dict_start]
    m = re.search(rb"(\d+)\s+\d+\s+obj\s*$", window)
    return int(m.group(1)) if m else None


_SKIP_STREAM_TOKENS = (b"/ObjStm", b"/XRef", b"/Image", b"FontFile")

# CID/Type0 字体特征（原始字节与 ObjStm 解压后同口径扫描；0.1.1 起含 ObjStm）
_CID_FONT_SIG_RE = re.compile(rb"/Subtype\s*/Type0\b|/Identity-[HV]|/CIDFontType[02]")

# 防线二（输出侧乱码兜底）阈值——刻意保守：干净文本（中英文、含少量替换符）
# 必须零误报；真乱码（如 Chrome/WPS 导出夹具）控制字符占比远超下限。
GARBAGE_CTRL_MIN_COUNT = 20      # 可疑字符绝对数下限
GARBAGE_CTRL_MIN_RATIO = 0.05    # 且占输出文本比例下限
GARBAGE_CID_TOKEN_MIN = 10       # (cid:N) 字面量数量下限（单独成警）


def _pdf_collect_streams(raw: bytes, warnings: List[str]) -> Dict[int, Tuple[bytes, bytes]]:
    """收集所有流：obj_num -> (dict_bytes, 未解压 payload)。"""
    streams: Dict[int, Tuple[bytes, bytes]] = {}
    for m in re.finditer(rb"(?<!end)stream(\r\n|\n|\r)", raw):
        found = _pdf_dict_backwards(raw, m.start())
        if found is None:
            continue
        dict_bytes, dict_start = found
        obj_num = _pdf_obj_num_before(raw, dict_start)
        if obj_num is None:
            continue
        data_start = m.end()
        end = raw.find(b"endstream", data_start)
        if end == -1:
            warnings.append("stream_decompress_failed: 存在未闭合的内容流，对应内容可能缺失")
            continue
        streams[obj_num] = (dict_bytes, raw[data_start:end].rstrip(b"\r\n"))
    return streams


def _pdf_decompress(dict_bytes: bytes, payload: bytes) -> Optional[bytes]:
    if b"FlateDecode" in dict_bytes:
        try:
            return zlib.decompress(payload)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(payload)
            except zlib.error:
                return None
    if re.search(rb"/Filter", dict_bytes):
        return None  # 非 Flate 过滤器（LZW/RunLength/DCT 等）不支持
    return payload


def _objstm_decode_supported(dict_bytes: bytes) -> bool:
    """ObjStm 仅支持裸 FlateDecode。带预测器（/DecodeParms）时不做解压——
    zlib 虽能膨胀但产物是预测器过滤数据，直接解析会静默得到垃圾对象；
    此类（含多级/非 Flate 过滤器，经 _pdf_decompress 失败路径）一律由调用方
    降级到防线二，不得静默跳过。"""
    if re.search(rb"/DecodeParms\b", dict_bytes):
        return False
    if b"FlateDecode" in dict_bytes:
        return True
    return not re.search(rb"/Filter\b", dict_bytes)


def _pdf_output_garbage_warning(text: str) -> Optional[str]:
    """防线二：对提取输出文本做 CID 乱码特征兜底检测（对任何成因成立）。

    命中返回与防线一同码的告警字符串（cid_font_limited_support: …），
    未命中返回 None。两类特征：
      a) (cid:N) 未映射字形字面量成批出现；
      b) C0 控制字符（制表/换行/回车/换页除外）、DEL/C1、U+FFFD 替换符
         合计超阈值（绝对数与占比双门槛，中文/英文正常文本不可能触达）。
    """
    if not text:
        return None
    cid_tokens = len(re.findall(r"\(cid:\d+\)", text))
    if cid_tokens >= GARBAGE_CID_TOKEN_MIN:
        return ("cid_font_limited_support: 输出文本含 %d 个 (cid:N) 未映射字形字面量，"
                "疑似 CID 字体乱码（输出侧兜底检测命中）" % cid_tokens)
    ctrl = 0
    for ch in text:
        o = ord(ch)
        if (o < 32 and ch not in "\t\n\r\f") or 0x7F <= o <= 0x9F or ch == "\ufffd":
            ctrl += 1
    if ctrl >= GARBAGE_CTRL_MIN_COUNT and ctrl / len(text) >= GARBAGE_CTRL_MIN_RATIO:
        return ("cid_font_limited_support: 输出文本控制字符/替换符占比异常"
                "（%d/%d），疑似 CID 字体乱码（输出侧兜底检测命中）" % (ctrl, len(text)))
    return None


def _pdf_parse_objstm(body: bytes) -> Dict[int, bytes]:
    """解析对象流（PDF 1.5+ 压缩 xref 常见），返回 obj_num -> 对象原始字节。

    偏移按规范相对 /First（自流数据起点计）；头部/偏移表解析失败或偏移越界
    时返回已解析部分（不抛错），调用方仍保有防线一的整段特征扫描。"""
    out: Dict[int, bytes] = {}
    try:
        head_end = body.find(b"\n")
        head = body[:head_end].split()
        n, first = int(head[0]), int(head[1])
        rest = body[head_end + 1:]
        nums: List[int] = []
        pos = 0
        pat = re.compile(rb"\s*(\d+)")
        while len(nums) < 2 * n:
            m = pat.match(rest, pos)
            if not m:
                return out
            nums.append(int(m.group(1)))
            pos = m.end()
        objnums, offsets = nums[0::2], nums[1::2]
        for k, onum in enumerate(objnums):
            start = first + offsets[k]
            end = first + offsets[k + 1] if k + 1 < n else len(body)
            if 0 <= start < end <= len(body):
                out[onum] = body[start:end]
    except (ValueError, IndexError):
        return out
    return out


def _pdf_raw_obj_body(raw: bytes, num: int) -> Optional[bytes]:
    m = re.search(rb"(?<!\d)%d\s+\d+\s+obj\b(.*?)endobj" % num, raw, re.DOTALL)
    return m.group(1) if m else None


def _pdf_page_order(raw: bytes, obj_bodies: Dict[int, bytes],
                    content_nums: List[int], warnings: List[str]) -> List[int]:
    """尽量按页面树还原页序；失败则按对象编号近似并告警。"""
    best: Optional[Tuple[int, List[int]]] = None  # (count, kids)
    for body in list(obj_bodies.values()) + [raw]:
        for m in re.finditer(rb"/Type\s*/Pages\b(.{0,800}?)>>", body, re.DOTALL):
            seg = m.group(1)
            km = re.search(rb"/Kids\s*\[([^\]]*)\]", seg)
            if not km:
                continue
            kids = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", km.group(1))]
            cm = re.search(rb"/Count\s+(\d+)", seg)
            count = int(cm.group(1)) if cm else len(kids)
            if best is None or count > best[0]:
                best = (count, kids)
    if not best or not best[1]:
        warnings.append("page_order_approximate: 无法解析页面树，按对象编号近似还原页序")
        return sorted(content_nums)

    def contents_refs(page_body: bytes) -> List[int]:
        single = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
        if single:
            return [int(single.group(1))]
        arr = re.search(rb"/Contents\s*\[([^\]]*)\]", page_body)
        if arr:
            return [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", arr.group(1))]
        return []

    ordered: List[int] = []
    known = set(content_nums)
    for kid in best[1]:
        body = obj_bodies.get(kid) or _pdf_raw_obj_body(raw, kid)
        if body is None:
            continue
        head = body[:1200]
        if re.search(rb"/Type\s*/Page\b", head):
            ordered.extend(n for n in contents_refs(body) if n in known)
        elif re.search(rb"/Type\s*/Pages\b", head):
            km = re.search(rb"/Kids\s*\[([^\]]*)\]", body)
            if km:
                for sub in re.findall(rb"(\d+)\s+\d+\s+R", km.group(1)):
                    sub_body = obj_bodies.get(int(sub)) or _pdf_raw_obj_body(raw, int(sub))
                    if sub_body is not None and re.search(rb"/Type\s*/Page\b", sub_body[:1200]):
                        ordered.extend(n for n in contents_refs(sub_body) if n in known)
    if not ordered:
        warnings.append("page_order_approximate: 页面树引用无法解析，按对象编号近似还原页序")
        return sorted(content_nums)
    if len(ordered) != len(set(content_nums)):
        warnings.append("page_order_approximate: 部分页面未纳入页面树，页序为近似还原")
        ordered += sorted(c for c in content_nums if c not in set(ordered))
    return ordered


def extract_pdf_data(data: bytes, warnings: List[str]) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """返回 (status, reason_code, extra)。status=ok 时 extra 含 text/blocks/summary。"""
    if len(data) == 0:
        return "insufficient_input", "empty_file", {}
    if b"%PDF" not in data[:1024]:
        return "insufficient_input", "corrupt_pdf", {}
    if re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        return "insufficient_input", "encrypted_pdf", {}

    local: List[str] = []
    streams = _pdf_collect_streams(data, local)
    content: Dict[int, bytes] = {}
    obj_bodies: Dict[int, bytes] = {}
    # 防线一：字体特征 = 原始字节 ∪ ObjStm 解压后字节（0.1.1 起覆盖压缩对象流）
    cid_font_seen = bool(_CID_FONT_SIG_RE.search(data))
    for onum, (dict_bytes, payload) in streams.items():
        if b"/ObjStm" in dict_bytes:
            if not _objstm_decode_supported(dict_bytes):
                local.append("stream_decompress_failed: 对象流(ObjStm)带预测器或多级过滤器，"
                             "无法解出内部对象（可能含字体定义），已降级到输出侧乱码检测")
                continue
            body = _pdf_decompress(dict_bytes, payload)
            parsed = _pdf_parse_objstm(body) if body else {}
            # 解压失败（含宽松回退产物解析不出对象）或对象数不足声明值＝事实失败：
            # 显式告警降级到防线二，不静默跳过。
            head_m = re.match(rb"\s*(\d+)", body) if body else None
            declared_n = int(head_m.group(1)) if head_m else 0
            if not parsed:
                local.append("stream_decompress_failed: 对象流(ObjStm)解压失败（流损坏），"
                             "内部对象可能缺失（可能含字体定义），已降级到输出侧乱码检测")
                continue
            if len(parsed) < declared_n:
                local.append("stream_decompress_failed: 对象流(ObjStm)仅部分对象可解析"
                             "（%d/%d），缺失对象可能含字体定义，已降级到输出侧乱码检测"
                             % (len(parsed), declared_n))
            obj_bodies.update(parsed)
            if _CID_FONT_SIG_RE.search(body):
                cid_font_seen = True
            continue
        if any(tok in dict_bytes for tok in _SKIP_STREAM_TOKENS):
            continue
        plain = _pdf_decompress(dict_bytes, payload)
        if plain is None:
            if b"FlateDecode" in dict_bytes:
                local.append("stream_decompress_failed: 部分内容流解压失败")
            continue
        is_form = re.search(rb"/Subtype\s*/Form\b", dict_bytes)
        is_plain_stream = (b"/Type" not in dict_bytes and b"/Subtype" not in dict_bytes)
        if is_form or is_plain_stream:
            content[onum] = plain

    if not content:
        if re.search(rb"/Subtype\s*/Image", data):
            return "insufficient_input", "scanned_pdf_suspected", {}
        return "insufficient_input", "corrupt_pdf", {}
    if cid_font_seen:
        local.append("cid_font_limited_support")

    pages = len(re.findall(rb"/Type\s*/Page\b", data))
    ordered = _pdf_page_order(data, obj_bodies, list(content.keys()), local)

    page_texts: List[str] = [_pdf_content_to_text(content[onum]) for onum in ordered]
    blocks: List[Dict[str, str]] = []
    for pno, ptext in enumerate(page_texts, start=1):
        for n, line in enumerate(ptext.split("\n"), start=1):
            if line.strip():
                blocks.append({"locator": f"P{pno}L{n}", "text": line})
    total_chars = sum(len(b["text"]) for b in blocks)

    page_guess = pages or len(page_texts) or 1
    if total_chars < SPARSE_CHARS_PER_PAGE * page_guess:
        return "insufficient_input", "scanned_pdf_suspected", {}

    text = "\n".join(pt for pt in page_texts if pt)
    # 防线二：字体特征没命中但输出本身是乱码 → 仍必须告警（「乱码必有告警」不变式，
    # 对任何成因成立）。防线一已命中时保持既有单条告警，不重复追加。
    if not cid_font_seen:
        garbage = _pdf_output_garbage_warning(text)
        if garbage:
            local.append(garbage)
    warnings.extend(local)
    summary = {"pages": pages or len(page_texts), "text_chars": total_chars, "blocks": len(blocks)}
    return "ok", None, {"text": text, "blocks": blocks, "summary": summary}


# ================= DOCX =================

def _docx_paragraph_texts(xml_bytes: bytes) -> List[str]:
    """按文档顺序取每个段落文本（含表格/文本框内段落；嵌套段落不重复计）。"""
    root = ET.fromstring(xml_bytes)
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    parent_map = {c: p for p in root.iter() for c in p}

    def nearest_p(node):
        cur = node
        while cur is not None:
            if cur.tag == W + "p":
                return cur
            cur = parent_map.get(cur)
        return None

    texts: List[str] = []
    for p in root.iter(W + "p"):
        parts: List[str] = []
        for node in p.iter():
            own = nearest_p(node) is p
            if node.tag == W + "t" and own:
                parts.append(node.text or "")
            elif node.tag == W + "tab" and own:
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr") and own:
                parts.append("\n")
        texts.append("".join(parts))
    return texts


def extract_docx_data(data: bytes, warnings: List[str]) -> Tuple[str, Optional[str], Dict[str, Any]]:
    if len(data) == 0:
        return "insufficient_input", "empty_file", {}
    if data[:8] == OLE_MAGIC:
        return "insufficient_input", "encrypted_or_legacy_doc", {}
    if data[:2] != b"PK":
        return "insufficient_input", "corrupt_docx", {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return "insufficient_input", "corrupt_docx", {}
    if "word/document.xml" not in zf.namelist():
        return "insufficient_input", "corrupt_docx", {}
    xml_bytes = zf.read("word/document.xml")
    truncated = False
    if len(xml_bytes) > MAX_XML_BYTES:
        warnings.append(f"output_truncated: document.xml 超过 {MAX_XML_BYTES} 字节，仅解析前段")
        xml_bytes = xml_bytes[:MAX_XML_BYTES]
        truncated = True
    try:
        paragraphs = _docx_paragraph_texts(xml_bytes)
    except ET.ParseError:
        return "insufficient_input", "corrupt_docx", {}

    blocks = [{"locator": f"¶{n}", "text": ptext}
              for n, ptext in enumerate(paragraphs, start=1) if ptext.strip()]
    total_chars = sum(len(b["text"]) for b in blocks)
    if total_chars == 0 and not truncated:
        # 有正文结构却无文字：大概率是图片型内容（扫描件贴进 Word）
        return "insufficient_input", "scanned_pdf_suspected", {}
    warnings_local = warnings
    summary = {"paragraphs": len(paragraphs), "text_chars": total_chars, "blocks": len(blocks)}
    text = "\n".join(b["text"] for b in blocks)
    return "ok", None, {"text": text, "blocks": blocks, "summary": summary}


# ================= 纯文本 =================

def extract_text_data(data: bytes, warnings: List[str]) -> Tuple[str, Optional[str], Dict[str, Any]]:
    if len(data) == 0:
        return "insufficient_input", "empty_file", {}
    try:
        text, enc_warnings = _decode_bytes(data)
    except UnicodeDecodeError:
        return "insufficient_input", "undecodable_text", {}
    warnings.extend(enc_warnings)
    if not text.strip():
        return "insufficient_input", "empty_file", {}
    blocks = _split_line_blocks(text, "L{n}")
    summary = {"lines": len(text.splitlines()), "text_chars": len(text), "blocks": len(blocks)}
    return "ok", None, {"text": text, "blocks": blocks, "summary": summary}


# ================= JD 链接 =================

def _strip_html(raw: str) -> str:
    txt = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    txt = re.sub(r"(?i)</?(p|div|br|li|tr|h[1-6]|section|article|table)\b[^>]*>", "\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = html_mod.unescape(txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    return txt.strip()


def extract_jd_url(url: str, warnings: List[str]) -> Tuple[str, Optional[str], Dict[str, Any]]:
    if not re.match(r"^https?://|^file://", url):
        return "insufficient_input", "link_fetch_failed", {}
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", None)
            if status is not None and status >= 400:
                return "insufficient_input", "link_fetch_failed", {}
            ctype = (resp.headers.get("Content-Type") or "").lower()
            payload = resp.read(MAX_URL_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return "insufficient_input", "link_fetch_failed", {}
    if len(payload) > MAX_URL_BYTES:
        return "insufficient_input", "link_content_too_large", {}
    if not payload.strip():
        return "insufficient_input", "empty_file", {}

    charset_m = re.search(r"charset=([\w-]+)", ctype)
    prefer = charset_m.group(1) if charset_m else None
    is_html = ("html" in ctype) or payload[:256].lstrip().lower().startswith((b"<!doctype html", b"<html"))
    try:
        text, enc_warnings = _decode_bytes(payload, prefer=prefer)
    except UnicodeDecodeError:
        return "insufficient_input", "link_not_readable", {}
    warnings.extend(enc_warnings)
    if is_html:
        text = _strip_html(text)
        warnings.append("html_content_stripped")
    if not text.strip():
        return "insufficient_input", "link_not_readable", {}
    blocks = _split_line_blocks(text, "L{n}")
    summary = {"url": url, "lines": len(text.splitlines()), "text_chars": len(text), "blocks": len(blocks)}
    return "ok", None, {"text": text, "blocks": blocks, "summary": summary}


# ================= 文件入口 =================

def extract_file(path: Path, kind: str) -> Dict[str, Any]:
    warnings: List[str] = []
    base: Dict[str, Any] = {
        "kind": kind,
        "filename": path.name,
        "path": str(path),
        "status": "insufficient_input",
        "reason_code": None,
        "guidance": None,
        "parse_warnings": warnings,
    }
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        base.update(reason_code="file_not_found", guidance=GUIDANCE["file_not_found"])
        return base
    except OSError:
        base.update(reason_code="file_not_found", guidance=GUIDANCE["file_not_found"])
        return base

    if data[:8] == OLE_MAGIC:
        base.update(reason_code="encrypted_or_legacy_doc", guidance=GUIDANCE["encrypted_or_legacy_doc"])
        return base

    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        fmt = "pdf"
    elif suffix in DOCX_SUFFIXES:
        fmt = "docx"
    elif suffix in TEXT_SUFFIXES:
        fmt = "text"
    elif data[:2] == b"PK":
        fmt = "docx"
    elif b"%PDF" in data[:1024]:
        fmt = "pdf"
    elif _looks_like_binary(data):
        base.update(reason_code="unsupported_format", guidance=GUIDANCE["unsupported_format"],
                    format="unknown")
        return base
    else:
        fmt = "text"  # 无识别特征时按文本尝试

    if fmt == "pdf":
        status, reason, extra = extract_pdf_data(data, warnings)
    elif fmt == "docx":
        status, reason, extra = extract_docx_data(data, warnings)
    else:
        status, reason, extra = extract_text_data(data, warnings)

    base["format"] = fmt
    base["status"] = status
    base["reason_code"] = reason
    base["guidance"] = GUIDANCE.get(reason)
    if status == "ok":
        extra["text"] = _cap_text(extra["text"], warnings)
        base["text"] = extra["text"]
        base["blocks"] = extra["blocks"]
        base["summary"] = extra["summary"]
    return base


def _looks_like_binary(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return True
    if not data:
        return False
    sample = data[:4096]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13) or b >= 128)
    return printable / len(sample) < 0.7


# ================= CLI =================

def run_extraction(resume_paths: List[Path], jd_paths: List[Path], jd_urls: List[str]) -> Dict[str, Any]:
    inputs: List[Dict[str, Any]] = []
    counters = {"resume": 0, "jd": 0}

    def push(entry: Dict[str, Any]) -> None:
        counters[entry["kind"]] += 1
        out = {"source_id": f"src-{entry['kind']}-{counters[entry['kind']]}"}
        out.update(entry)
        inputs.append(out)

    for p in resume_paths:
        push(extract_file(p, "resume"))
    for p in jd_paths:
        push(extract_file(p, "jd"))
    for u in jd_urls:
        warnings: List[str] = []
        status, reason, extra = extract_jd_url(u, warnings)
        entry: Dict[str, Any] = {
            "kind": "jd",
            "filename": u.rstrip("/").rsplit("/", 1)[-1] or u,
            "path": u,
            "format": "url",
            "status": status,
            "reason_code": reason,
            "guidance": GUIDANCE.get(reason),
            "parse_warnings": warnings,
        }
        if status == "ok":
            extra["text"] = _cap_text(extra["text"], warnings)
            entry["text"] = extra["text"]
            entry["blocks"] = extra["blocks"]
            entry["summary"] = extra["summary"]
        push(entry)

    return {
        "extraction_version": EXTRACTION_VERSION,
        "ready_for_analysis": bool(inputs) and all(i["status"] == "ok" for i in inputs),
        "inputs": inputs,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="T2 材料提取与来源定位（PDF/DOCX/文本/JD 链接）")
    ap.add_argument("--resume", metavar="FILE", action="append", default=[], help="简历文件，可重复")
    ap.add_argument("--jd-file", metavar="FILE", action="append", default=[], help="JD 文件，可重复")
    ap.add_argument("--jd-url", metavar="URL", action="append", default=[], help="JD 链接，可重复")
    ap.add_argument("--output", metavar="FILE", default=None, help="输出 JSON 路径（缺省 stdout）")
    args = ap.parse_args(argv)

    if not (args.resume or args.jd_file or args.jd_url):
        ap.error("至少提供一个输入：--resume / --jd-file / --jd-url")

    result = run_extraction(
        [Path(p) for p in args.resume],
        [Path(p) for p in args.jd_file],
        list(args.jd_url),
    )
    out_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out_text + "\n", encoding="utf-8")
    else:
        print(out_text)

    bad = [i for i in result["inputs"] if i["status"] != "ok"]
    print(f"\n提取完成：{len(result['inputs']) - len(bad)}/{len(result['inputs'])} 个输入就绪"
          f"（ready_for_analysis={result['ready_for_analysis']}）", file=sys.stderr)
    for i in bad:
        print(f"  ✗ [{i['source_id']}] {i['filename']}: {i['reason_code']} → {i['guidance']}", file=sys.stderr)
    for i in result["inputs"]:
        for w in i["parse_warnings"]:
            print(f"  ⚠ [{i['source_id']}] {w}", file=sys.stderr)
            code = w.split(":", 1)[0]
            if code in WARNING_GUIDANCE and i["status"] == "ok":
                print(f"     {WARNING_GUIDANCE[code]}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
