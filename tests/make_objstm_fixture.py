# -*- coding: utf-8 -*-
"""构造「字体字典位于压缩对象流（ObjStm）内」的中文 PDF 夹具（T5R/MYW-66 回归用）。

背景：T5 实测（MYW-63）发现 Chrome 打印 / 新版 Word / WPS 导出的新式 PDF 会把
字体等非流对象压进 ObjStm，提取器旧检测只扫文件原始字节 → CID 乱码无告警。
本机没有 WPS / 新版 Word 可导出真件，按 MYW-66 授权用脚本构造同构变体：
  * Catalog / Pages / Page / Font(Type0+Identity-H) / FontDescriptor 全部放进 ObjStm
    （与 Word/WPS 导出的对象布局同类）；
  * 页面内容流在 ObjStm 外，用 2 字节 GID 十六进制串绘字（无 ToUnicode 可解码），
    提取输出与真实 Chrome/WPS 中文导出一样是 CID 字节乱码；
  * 对象编号 / 偏移全部确定性生成，同脚本必出同字节。

用法：
  python3 tests/make_objstm_fixture.py [输出路径]
  缺省写到 docs/evidence/pdf-multicolumn/resume-objstm-constructed.pdf

变体（仅测试用，不入库）：
  build_objstm_pdf(corrupt=True)     → ObjStm Flate 载荷损坏（解压失败 → 须降级防线二）
  build_objstm_pdf(predictor=True)   → ObjStm 带 /Predictor 12（不支持 → 须降级防线二）
"""
import re
import sys
import zlib
from pathlib import Path

RESUME_LINES = [
    "李晓晓",
    "求职意向：新媒体运营",
    "教育经历：华东大学 市场营销 本科 2022-2026",
    "实习经历：某消费品牌 新媒体运营实习生",
    "技能：小红书内容运营、 SQL 、 Python 基础",
]


def _gid_hex(text: str) -> str:
    """把文本编码为 2 字节假 GID 十六进制串（首字节 0x01，latin-1 解码即控制字符）。"""
    return "".join("%02X%02X" % (1, (ord(ch) * 7 + 13) % 256) for ch in text)


def _content_stream() -> bytes:
    parts = ["BT /F1 12 Tf 14 TL 72 720 Td"]
    for line in RESUME_LINES:
        parts.append("<%s> Tj T*" % _gid_hex(line))
    parts.append("ET")
    return " ".join(parts).encode("ascii")


def _objstm_of(objects: dict) -> bytes:
    """把 {obj_num: dict_bytes} 打包成规范 ObjStm 体（首行 `N First` + 偏移表 + 对象区）。

    偏移按 PDF 规范相对 /First（自流数据起点计），首行两个整数与字典 /First
    同值（定长不动点求出），与 extract_resume._pdf_parse_objstm 的规范语义一致。"""
    nums = sorted(objects)
    bodies = b"".join(objects[n] for n in nums)
    pairs, offset = [], 0
    for n in nums:
        pairs.append(b"%d %d" % (n, offset))
        offset += len(objects[n])
    table = b" ".join(pairs)
    head = b"%d 0" % len(nums)
    while True:  # First 写进首行会改变首行长度，迭代到定长（通常 1-2 轮）
        first = len(head) + 1 + len(table) + 1
        nxt = b"%d %d" % (len(nums), first)
        if nxt == head:
            break
        head = nxt
    return head + b"\n" + table + b"\n" + bodies


def build_objstm_pdf(corrupt: bool = False, predictor: bool = False) -> bytes:
    """生成 ObjStm 夹具 PDF；corrupt/predictor 构造防线一必须降级的两个变体。"""
    objects = {  # 放入 ObjStm 的非流对象（字典均写入原始字节扫不到的压缩区）
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
           b"/Resources << /Font << /F1 4 0 R >> >> /Contents 7 0 R >>",
        4: b"<< /Type /Font /Subtype /Type0 /BaseFont /FFFFAA+SimSun-Identity-H "
           b"/Encoding /Identity-H /DescendantFonts [5 0 R] >>",
        5: b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /FFFFAA+SimSun "
           b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
           b"/FontDescriptor 6 0 R /DW 1000 >>",
        6: b"<< /Type /FontDescriptor /FontName /FFFFAA+SimSun /Flags 4 "
           b"/FontBBox [0 -200 1000 900] /ItalicAngle 0 /StemV 90 >>",
    }
    stm_raw = _objstm_of(objects)
    stm_first = int(stm_raw.split(b"\n", 1)[0].split()[1])
    if predictor:  # PNG 预测器：本工具不支持解压，必须降级（数据本身不再要求可读）
        row = bytearray(len(stm_raw) + (16 - len(stm_raw) % 16) % 16 + 1)
        row[0::17] = b"\x02" * len(row[0::17])
        row[1:1 + len(stm_raw)] = stm_raw
        stm_payload = zlib.compress(bytes(row))
        stm_dict = (b"<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode "
                    b"/DecodeParms << /Predictor 12 /Colors 1 /Columns 16 >> /Length %%d >>"
                    % (len(objects), stm_first))
    else:
        stm_payload = zlib.compress(stm_raw)
        stm_dict = (b"<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %%d >>"
                    % (len(objects), stm_first))
    if corrupt:  # 模拟流损坏：破坏 Flate 载荷前段（校验和之前的压缩数据本身），
        # 使 zlib 严格解压与宽松回退都无法恢复出完整对象区
        stm_payload = stm_payload[:8] + bytes(b ^ 0xFF for b in stm_payload[8:40]) + stm_payload[40:]
    stm_dict = stm_dict % len(stm_payload)

    content = zlib.compress(_content_stream())
    raw_objs = {
        7: b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream",
        8: stm_dict + b"\nstream\n" + stm_payload + b"\nendstream",
    }

    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(raw_objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + raw_objs[num] + b"\nendobj\n"
    xref_at = len(out)
    mx = max(raw_objs)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (mx + 1)
    for num in range(1, mx + 1):
        out += b"%010d 00000 n \n" % offsets.get(num, 0)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (mx + 1, xref_at)
    return bytes(out)


if __name__ == "__main__":
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parents[1] / "docs/evidence/pdf-multicolumn/resume-objstm-constructed.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_objstm_pdf())
    print("written:", out_path, out_path.stat().st_size, "bytes")
