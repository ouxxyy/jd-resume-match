# -*- coding: utf-8 -*-
"""T2 提取测试：文本/PDF/DOCX/JD 链接的正路径与全部降级路径（坏输入不静默误读）。"""
import io
import json
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract_resume as er  # noqa: E402


# ---------- 测试夹具构建 ----------

def build_pdf(page_texts, encrypt=False, scanned=False, cid=False, garbage_xref=False):
    """构造最小合法 PDF：页树 + Flate 内容流；可注入加密/图片/CID 字体特征。"""
    objs = {}
    n = len(page_texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    nxt = 3 + 2 * n
    for i, body in enumerate(page_texts):
        comp = zlib.compress(body)
        objs[3 + 2 * i] = f"<< /Type /Page /Parent 2 0 R /Contents {4 + 2 * i} 0 R >>".encode()
        objs[4 + 2 * i] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(comp) + comp + b"\nendstream"
    if scanned:
        objs[nxt] = b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 >>\nstream\n" + b"\x00" * 8 + b"\nendstream"
        nxt += 1
    if cid:
        objs[nxt] = b"<< /Type /Font /Subtype /Type0 /BaseFont /SimSun-Identity-H /Encoding /Identity-H >>"
        nxt += 1
    enc_ref = b""
    if encrypt:
        objs[nxt] = b"<< /Filter /Standard /V 1 /R 2 /O (oooo) /U (uuuu) /P -1 >>"
        enc_ref = b" /Encrypt %d 0 R" % nxt
        nxt += 1
    out = bytearray(b"%PDF-1.4\n")
    offs = {}
    for num in sorted(objs):
        offs[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_at = len(out)
    mx = max(objs)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (mx + 1)
    for num in range(1, mx + 1):
        out += b"%010d 00000 n \n" % offs.get(num, 0)
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (mx + 1, enc_ref, xref_at)
    return bytes(out)


def build_docx(paragraphs, with_document=True):
    buf = io.BytesIO()
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        if with_document:
            z.writestr("word/document.xml", f"<?xml version='1.0'?><w:document {ns}><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


P1 = (b"BT /F1 12 Tf 72 720 Td (Name: Li Xiaoxiao, fresh graduate in marketing) Tj "
      b"0 -14 Td (Education: B.S. Marketing 2022-2026) Tj "
      b"0 -14 Td (Skill: Python \\(3 years\\)) Tj "
      b"0 -14 Td (octal A = \\101) Tj ET")
P2 = b"BT /F1 12 Tf 72 700 Td (Internship: new media operations at a consumer brand) Tj ET"


class TempFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        p = self.tmp / name
        p.write_bytes(data)
        return p


# ---------- 文本 ----------

class TestText(TempFileTest):
    def test_utf8_and_locators(self):
        p = self.write("resume.md", "# 李晓晓\n\n技能：SQL、Python\n实习：新媒体运营\n".encode("utf-8"))
        status, reason, extra = er.extract_text_data(p.read_bytes(), [])
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(extra["blocks"][0], {"locator": "L1", "text": "# 李晓晓"})
        self.assertEqual(len(extra["blocks"]), 3)

    def test_gb18030_fallback_warns(self):
        p = self.write("old.txt", "姓名：王成，应聘数据分析师".encode("gb18030"))
        warnings = []
        status, reason, extra = er.extract_text_data(p.read_bytes(), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertTrue(any(w.startswith("encoding_fallback") for w in warnings))
        self.assertIn("王成", extra["text"])

    def test_empty_and_blank(self):
        for data in (b"", b"  \n\t \r\n"):
            status, reason, _ = er.extract_text_data(data, [])
            self.assertEqual((status, reason), ("insufficient_input", "empty_file"), data)

    def test_undecodable(self):
        status, reason, _ = er.extract_text_data(b"\xff\xfe\xfa\x81\x9cDog\xc3", [])
        self.assertEqual((status, reason), ("insufficient_input", "undecodable_text"))


# ---------- PDF ----------

class TestPdf(TempFileTest):
    def test_normal_pdf_text_locators_and_escapes(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_pdf([P1, P2]), warnings)
        self.assertEqual((status, reason), ("ok", None), warnings)
        self.assertEqual(extra["summary"]["pages"], 2)
        locators = [b["locator"] for b in extra["blocks"]]
        self.assertEqual(locators, ["P1L1", "P1L2", "P1L3", "P1L4", "P2L1"])
        self.assertIn("Python (3 years)", extra["text"], "转义括号必须还原")
        self.assertIn("octal A = A", extra["text"], "八进制转义必须解码")
        self.assertLess(extra["text"].index("Name:"), extra["text"].index("Internship:"), "页序必须正确")

    def test_encrypted_pdf_rejected(self):
        status, reason, _ = er.extract_pdf_data(build_pdf([P1, P2], encrypt=True), [])
        self.assertEqual((status, reason), ("insufficient_input", "encrypted_pdf"))

    def test_scanned_pdf_rejected_not_silent(self):
        status, reason, _ = er.extract_pdf_data(
            build_pdf([b"0 0 1 RG 10 10 m 20 20 l S"], scanned=True), [])
        self.assertEqual((status, reason), ("insufficient_input", "scanned_pdf_suspected"))

    def test_empty_text_pages_rejected(self):
        status, reason, _ = er.extract_pdf_data(build_pdf([b"", b""]), [])
        self.assertEqual(status, "insufficient_input")

    def test_corrupt_pdf(self):
        for data in (b"not a pdf at all " * 10, b""):
            status, reason, _ = er.extract_pdf_data(data, [])
            self.assertEqual(status, "insufficient_input", data)
            self.assertIn(reason, ("corrupt_pdf", "empty_file"))

    def test_cid_font_warns_but_extracts(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_pdf([P1, P2], cid=True), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertTrue(any(w.startswith("cid_font_limited_support") for w in warnings),
                        "CID 字体必须显式告警，不得静默乱码")
        self.assertIn("Li Xiaoxiao", extra["text"])


# ---------- DOCX ----------

class TestDocx(TempFileTest):
    def test_docx_chinese_paragraphs_and_locators(self):
        data = build_docx(["姓名：王成", "技能：SQL、Python", "实习：数据分析"])
        warnings = []
        status, reason, extra = er.extract_docx_data(data, warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual([b["locator"] for b in extra["blocks"]], ["¶1", "¶2", "¶3"])
        self.assertEqual(extra["blocks"][0]["text"], "姓名：王成")

    def test_docx_missing_document_xml(self):
        status, reason, _ = er.extract_docx_data(build_docx(["x"], with_document=False), [])
        self.assertEqual((status, reason), ("insufficient_input", "corrupt_docx"))

    def test_docx_not_a_zip(self):
        status, reason, _ = er.extract_docx_data(b"garbage not a zip" * 8, [])
        self.assertEqual((status, reason), ("insufficient_input", "corrupt_docx"))

    def test_legacy_or_encrypted_doc(self):
        status, reason, _ = er.extract_docx_data(er.OLE_MAGIC + b"\x00" * 64, [])
        self.assertEqual((status, reason), ("insufficient_input", "encrypted_or_legacy_doc"))


# ---------- JD 链接 ----------

class TestUrl(TempFileTest):
    def test_file_url_success(self):
        p = self.write("jd.txt", "岗位职责：负责用户增长\n任职要求：熟悉 SQL\n".encode("utf-8"))
        warnings = []
        status, reason, extra = er.extract_jd_url(p.as_uri(), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertIn("用户增长", extra["text"])
        self.assertEqual(extra["blocks"][0]["locator"], "L1")

    def test_file_url_html_stripped_with_warning(self):
        p = self.write("jd.html", "<html><head><style>.x{}</style></head><body>"
                                  "<nav>首页</nav><h1>产品助理</h1><p>负责需求文档与验收</p>"
                                  "<script>evil()</script></body></html>".encode("utf-8"))
        warnings = []
        status, reason, extra = er.extract_jd_url(p.as_uri(), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertTrue(any(w.startswith("html_content_stripped") for w in warnings))
        self.assertIn("负责需求文档与验收", extra["text"])
        self.assertNotIn("<p>", extra["text"])
        self.assertNotIn("evil()", extra["text"])

    def test_fetch_failure_degrades(self):
        warnings = []
        status, reason, _ = er.extract_jd_url("http://127.0.0.1:9/jd", warnings)
        self.assertEqual((status, reason), ("insufficient_input", "link_fetch_failed"))
        self.assertTrue(er.GUIDANCE["link_fetch_failed"])

    def test_non_http_scheme_rejected(self):
        status, reason, _ = er.extract_jd_url("ftp://example.com/jd", [])
        self.assertEqual((status, reason), ("insufficient_input", "link_fetch_failed"))


# ---------- extract_file / run_extraction ----------

class TestEntry(TempFileTest):
    def test_file_not_found(self):
        entry = er.extract_file(self.tmp / "missing.pdf", "resume")
        self.assertEqual(entry["reason_code"], "file_not_found")
        self.assertTrue(entry["guidance"])

    def test_doc_suffix_ole_magic(self):
        p = self.write("resume.doc", er.OLE_MAGIC + b"\x00" * 32)
        self.assertEqual(er.extract_file(p, "resume")["reason_code"], "encrypted_or_legacy_doc")

    def test_unsupported_binary(self):
        p = self.write("resume.xlsx", b"PK\x03\x04" + b"\x00" * 200 + b"word/" + b"\x00" * 32)
        # xlsx 是 zip：按 docx 尝试会因缺 word/document.xml 判损坏，而不是静默出文本
        entry = er.extract_file(p, "resume")
        self.assertEqual(entry["status"], "insufficient_input")

    def test_run_extraction_ready_flag_and_ids(self):
        r = self.write("resume.md", "李晓晓的简历，新媒体运营实习经历".encode("utf-8"))
        j1 = self.write("jd1.txt", "岗位：新媒体运营，要求熟悉小红书".encode("utf-8"))
        out = er.run_extraction([r], [j1], [])
        self.assertTrue(out["ready_for_analysis"])
        self.assertEqual([i["source_id"] for i in out["inputs"]],
                         ["src-resume-1", "src-jd-1"])
        bad = self.write("bad.pdf", b"garbage" * 20)
        out2 = er.run_extraction([r], [j1, bad], [])
        self.assertFalse(out2["ready_for_analysis"])
        self.assertEqual(out2["inputs"][2]["reason_code"], "corrupt_pdf")

    def test_cli_exit_code_reflects_degradation(self):
        import subprocess
        r = self.write("resume.md", "内容".encode("utf-8"))
        bad = self.write("bad.pdf", b"junk" * 40)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/extract_resume.py"),
             "--resume", str(r), "--jd-file", str(bad)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, "有降级输入时退出码必须是 1")
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ready_for_analysis"])


if __name__ == "__main__":
    unittest.main()
