# -*- coding: utf-8 -*-
"""T5R（MYW-66）回归：ObjStm 压缩字体 PDF 静默乱码告警缺失回修。

双向锁定：
  * 乱码必告警 —— Chrome 打印夹具（Type3+CIDToGIDMap，防线二命中）、ObjStm 构造
    夹具（防线一命中）、ObjStm 损坏/预测器变体（降级 + 防线二命中）；
  * 干净必不告警 —— 干净英文 PDF、4 黄金案例 MD/DOCX 提取零误报；
  * 正样本去重锁 —— 原始字节 CID 特征 PDF 恰好 1 条告警，行为与 0.1.0 逐字一致。
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import extract_resume as er  # noqa: E402
from make_objstm_fixture import build_objstm_pdf  # noqa: E402
from test_extract_resume import P1, P2, build_docx, build_pdf  # noqa: E402

CHROME_FIXTURE = ROOT / "docs/evidence/pdf-multicolumn/resume-2col-zh.pdf"
CONSTRUCTED_FIXTURE = ROOT / "docs/evidence/pdf-multicolumn/resume-objstm-constructed.pdf"


def cid_warnings(warnings):
    return [w for w in warnings if w.split(":", 1)[0].strip() == "cid_font_limited_support"]


class TempFileTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------- 乱码必告警 ----------

class TestGarbageMustWarn(unittest.TestCase):
    def test_chrome_type3_fixture_warns_via_output_detection(self):
        """MYW-63 实测静默乱码的 Chrome 夹具（字体字典非 ObjStm、原始字节无 CID 特征）
        由防线二命中：修复前本用例失败（无告警）。"""
        raw = CHROME_FIXTURE.read_bytes()
        self.assertFalse(er._CID_FONT_SIG_RE.search(raw),
                         "前置：该夹具原始字节必须无 CID 特征（回归的是防线二）")
        warnings = []
        status, reason, extra = er.extract_pdf_data(raw, warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(len(cid_warnings(warnings)), 1, "恰一条 cid 告警")
        self.assertIn("输出侧兜底检测命中", warnings[-1])

    def test_objstm_constructed_fixture_warns_via_font_scan(self):
        """脚本构造的 ObjStm 夹具（字体字典在压缩对象流内，模拟 Word/WPS 导出布局）
        由防线一命中：修复前本用例失败。"""
        raw = CONSTRUCTED_FIXTURE.read_bytes()
        self.assertFalse(er._CID_FONT_SIG_RE.search(raw),
                         "前置：字体对象在 ObjStm 内，原始字节扫不到")
        warnings = []
        status, reason, extra = er.extract_pdf_data(raw, warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(cid_warnings(warnings), ["cid_font_limited_support"],
                         "防线一命中＝裸告警恰一条，防线二去重不追加")
        self.assertNotIn("page_order_approximate", [w.split(":")[0] for w in warnings],
                         "规范 ObjStm 的页面树应可解析，页序告警不得出现")

    def test_objstm_corrupt_degrades_without_crash_and_still_warns(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_objstm_pdf(corrupt=True), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertTrue(any(w.startswith("stream_decompress_failed") for w in warnings),
                        "ObjStm 解压失败必须显式降级告警，不得静默跳过")
        self.assertEqual(len(cid_warnings(warnings)), 1, "降级后防线二必须兜底告警")

    def test_objstm_predictor_degrades_without_crash_and_still_warns(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_objstm_pdf(predictor=True), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertTrue(any("预测器" in w for w in warnings), "预测器必须显式降级告警")
        self.assertEqual(len(cid_warnings(warnings)), 1)

    def test_cli_surfaces_warning_and_guidance(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/extract_resume.py"),
             "--resume", str(CHROME_FIXTURE)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, "提取状态 ok，退出码 0")
        payload = json.loads(proc.stdout)
        entry = payload["inputs"][0]
        self.assertTrue(any(w.startswith("cid_font_limited_support")
                            for w in entry["parse_warnings"]))
        self.assertIn("cid_font_limited_support", proc.stderr)
        self.assertIn("改用 DOCX", proc.stderr, "必须附带改贴文本/改用 DOCX 指引")


# ---------- 防线实现白盒 ----------

class TestDefenseInternals(TempFileTest):
    def test_objstm_parser_spec_offsets(self):
        from make_objstm_fixture import _objstm_of
        objects = {1: b"<< /A 1 >>", 2: b"<< /B 22 >>", 3: b"<< /C 333 >>"}
        body = _objstm_of(objects)
        parsed = er._pdf_parse_objstm(body)
        self.assertEqual(parsed, objects, "偏移按 First 语义必须逐对象还原")

    def test_objstm_parser_rejects_out_of_range_offsets(self):
        body = b"2 99999\n1 0 2 4\n<</X>><</Y>>"
        parsed = er._pdf_parse_objstm(body)
        self.assertEqual(parsed, {}, "越界偏移不得产出垃圾对象")

    def test_decode_support_matrix(self):
        self.assertTrue(er._objstm_decode_supported(b"<< /Filter /FlateDecode >>"))
        self.assertTrue(er._objstm_decode_supported(b"<< >>"))
        self.assertFalse(er._objstm_decode_supported(
            b"<< /Filter /FlateDecode /DecodeParms << /Predictor 12 >> >>"),
            "预测器不支持，必须走降级")
        self.assertFalse(er._objstm_decode_supported(b"<< /Filter /LZWDecode >>"))

    def test_output_garbage_detector_thresholds(self):
        fire = er._pdf_output_garbage_warning
        # (cid:N) 字面量：≥10 告警，9 条保守不告警
        self.assertIsNotNone(fire(" ".join("(cid:%d)" % i for i in range(10))))
        self.assertIsNone(fire(" ".join("(cid:%d)" % i for i in range(9))))
        # 控制字符乱码：绝对数 + 占比双门槛
        garbage = "".join(chr(b) for b in b"\x01\x02\x1f\x8f" * 60) + "正文" * 20
        self.assertIsNotNone(fire(garbage))
        # 干净中英文、少量替换符、仅制表/换行/换页：一律不告警
        self.assertIsNone(fire("姓名：王成，技能 SQL、Python，实习新媒体运营。" * 20))
        self.assertIsNone(fire("Name: Li Xiaoxiao, B.S. Marketing 2022-2026. " * 20))
        self.assertIsNone(fire("正常正文" * 500 + "\ufffd\ufffd\ufffd"),
                          "两千字里 3 个替换符＝正常文本，不得误报")
        self.assertIsNone(fire("a\tb\nc\fd" * 200))
        self.assertIsNone(fire(""))
        # 阈值边界：恰达双门槛（20 个、占比 5.0%）即告警（锁保守阈值的确定性）
        self.assertIsNotNone(fire("正常" + "\ufffd" * 20 + "x" * 378))


# ---------- 干净必不告警（误报红线） ----------

class TestCleanMustStaySilent(TempFileTest):
    def test_clean_english_pdf_no_warning(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_pdf([P1, P2]), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(cid_warnings(warnings), [])
        self.assertIn("Li Xiaoxiao", extra["text"])

    def test_golden_case_text_extraction_no_warning(self):
        """4 黄金案例的材料提取（MD/文本路径）保持现有行为：零 cid 告警。"""
        cases = [
            ROOT / "examples/case-a-freshgrad-ops/resume.md",
            ROOT / "examples/case-a-freshgrad-ops/jd-1-ops.md",
            ROOT / "examples/case-b-2yr-data-dev/resume.md",
            ROOT / "examples/supplements/sup-market-jd.md",
            ROOT / "examples/supplements/sup-design-jd.md",
        ]
        for p in cases:
            entry = er.extract_file(p, "resume")
            self.assertEqual(entry["status"], "ok", p.name)
            self.assertEqual(cid_warnings(entry["parse_warnings"]), [], str(p))

    def test_docx_chinese_no_warning(self):
        warnings = []
        status, reason, extra = er.extract_docx_data(
            build_docx(["姓名：李晓晓", "技能：SQL、Python", "实习：新媒体运营"]), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(cid_warnings(warnings), [])


# ---------- 正样本去重锁（0.1.0 行为逐字保持） ----------

class TestPositiveDedupLock(unittest.TestCase):
    def test_raw_cid_font_pdf_single_warning(self):
        warnings = []
        status, reason, extra = er.extract_pdf_data(build_pdf([P1, P2], cid=True), warnings)
        self.assertEqual((status, reason), ("ok", None))
        self.assertEqual(cid_warnings(warnings), ["cid_font_limited_support"],
                         "原始字节正样本：恰一条裸告警，与 0.1.0 完全一致")
        self.assertIn("Li Xiaoxiao", extra["text"])

    def test_version_bumped(self):
        self.assertEqual(er.EXTRACTION_VERSION, "jd-extract/0.1.1")


if __name__ == "__main__":
    unittest.main()
