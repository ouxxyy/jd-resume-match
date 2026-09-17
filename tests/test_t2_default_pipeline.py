# -*- coding: utf-8 -*-
"""test_t2_default_pipeline.py — MYW-72/MYW-73 T2 默认交付链路行为测试。

覆盖：编排契约 0.2.0（成员版内容组 + 渲染级脱敏白名单 + 0.1.0 读取兼容）、
成员版/案例版双套卡片、失败处理（缺失即报错，不回退旧模板）、
品牌配置独立、T1 已验收视觉与表达规则的移植回归。
黄金分数基线由 test_golden_cases.py 管辖；本文件不改任何评分断言。
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_editorial as red  # noqa: E402

REPORT_A = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))
ED_A = json.loads((ROOT / "examples/case-a-freshgrad-ops/editorial.json").read_text(encoding="utf-8"))
ED_B = json.loads((ROOT / "examples/case-b-2yr-data-dev/editorial.json").read_text(encoding="utf-8"))
REPORT_B = json.loads((ROOT / "examples/case-b-2yr-data-dev/expected.json").read_text(encoding="utf-8"))


def _bundle(tmp: Path, report=None, ed=None):
    return red.generate_bundle(report or copy.deepcopy(REPORT_A), ed or copy.deepcopy(ED_A), tmp)


class TestEditorialContractV2(unittest.TestCase):
    """0.2.0 编排契约：成员版必填、redactions 白名单、0.1.0 兼容读取。"""

    def test_case_a_v2_and_legacy_b_validate(self):
        self.assertEqual(red.validate_editorial(REPORT_A, ED_A), [])
        self.assertEqual(ED_A["editorial_version"], "jd-match-editorial/0.2.0")
        self.assertEqual(red.validate_editorial(REPORT_B, ED_B), [],
                         "0.1.0 旧编排必须保持可读取渲染（案例卡照旧）")

    def test_v2_requires_member_card(self):
        data = copy.deepcopy(ED_A)
        del data["member_card"]
        errors = red.validate_editorial(REPORT_A, data)
        self.assertTrue(any("member_card" in e for e in errors), errors)

    def test_v1_rejects_member_card(self):
        data = copy.deepcopy(ED_B)
        data["member_card"] = {"findings": [], "action": {"text": "x"}}
        errors = red.validate_editorial(REPORT_B, data)
        self.assertTrue(any("member_card" in e for e in errors), errors)

    def test_v2_requires_two_or_three_findings(self):
        data = copy.deepcopy(ED_A)
        data["member_card"]["findings"] = data["member_card"]["findings"][:1]
        errors = red.validate_editorial(REPORT_A, data)
        self.assertTrue(any("2–3" in e for e in errors), errors)

    def test_redactions_shape_validated(self):
        data = copy.deepcopy(ED_A)
        data["redactions"] = [{"from": "某省大学"}]
        errors = red.validate_editorial(REPORT_A, data)
        self.assertTrue(any("redactions[0]" in e for e in errors), errors)


class TestDualCardSets(unittest.TestCase):
    """成员版默认 1 张 + 案例版按编排启用；两者共用评分结果，不另算分。"""

    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_v2_bundle_emits_member_card(self):
        m = _bundle(self.tmp)
        self.assertIsNotNone(m["member_card"])
        self.assertEqual(m["member_card"].name, "member-card-01.html")
        self.assertTrue(m["member_card"].exists())

    def test_v1_bundle_emits_no_member_card(self):
        m = red.generate_bundle(REPORT_B, copy.deepcopy(ED_B), self.tmp)
        self.assertIsNone(m["member_card"])

    def test_member_card_content_and_brand(self):
        m = _bundle(self.tmp)
        html = m["member_card"].read_text(encoding="utf-8")
        self.assertIn("75", html)                       # 分数只来自报告 share_payload
        self.assertIn("简历证据匹配度", html)
        self.assertIn("建议：改好再投", html)            # SUGGESTION_HUMAN，渲染层固定映射
        self.assertIn("1 项硬门槛待核实", html)          # 门槛注记从报告门槛状态推导（case-a 有 1 项 pending）
        self.assertIn("核心优势", html)
        self.assertIn("核心缺口", html)                  # 优势与缺口并陈
        brand = json.loads((ROOT / "references/brand.json").read_text(encoding="utf-8"))
        self.assertIn(brand["search_entry"], html)      # 品牌入口来自 brand.json
        self.assertIn(brand["cta"], html)

    def test_member_card_canvas_1080_1440(self):
        m = _bundle(self.tmp)
        html = m["member_card"].read_text(encoding="utf-8")
        self.assertIn("width:1080px", html)
        self.assertIn("height:1440px", html)

    def test_member_card_no_private_markers(self):
        m = _bundle(self.tmp)
        html = re.sub(r"<[^>]+>", "", m["member_card"].read_text(encoding="utf-8"))
        for marker in REPORT_A["private_markers"]:
            self.assertNotIn(marker, html, f"成员卡不得出现私密标记 {marker}")

    def test_member_card_privacy_lint(self):
        data = copy.deepcopy(ED_A)
        data["member_card"]["findings"][0]["text"] = "联系李晓晓详聊内推机会"
        errors = red.validate_editorial(REPORT_A, data)
        self.assertTrue(any("李晓晓" in e for e in errors), errors)

    def test_member_card_digit_must_trace(self):
        data = copy.deepcopy(ED_A)
        data["member_card"]["findings"][0]["text"] = "单篇阅读 99999，全网第一"
        errors = red.validate_editorial(REPORT_A, data)
        self.assertTrue(any("99999" in e for e in errors), errors)

    def test_gate_note_three_tones(self):
        """门槛注记三态只从报告门槛状态推导：全过=green、待确认=amber、未过=red。"""
        base = {"jobs": [{"job_id": "j1", "gates": []}], "primary_job_id": "j1"}
        note, tone = red._member_gate_note({"jobs": [{"job_id": "j1", "gates": [
            {"gate_id": "g1", "status": "met"}]}], "primary_job_id": "j1"})
        self.assertEqual((tone, "全部通过" in note), ("green", True))
        note, tone = red._member_gate_note({"jobs": [{"job_id": "j1", "gates": [
            {"gate_id": "g1", "status": "pending_confirmation"}]}], "primary_job_id": "j1"})
        self.assertEqual((tone, "待核实" in note), ("amber", True))
        note, tone = red._member_gate_note({"jobs": [{"job_id": "j1", "gates": [
            {"gate_id": "g1", "status": "met"}, {"gate_id": "g2", "status": "unmet"}]}], "primary_job_id": "j1"})
        self.assertEqual((tone, "未满足" in note), ("red", True))


class TestRenderRedactions(unittest.TestCase):
    """渲染级脱敏白名单：声明即应用并复查，漏网即拒绝；不声明按成员私有件处理。"""

    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_redaction_applied_to_report(self):
        m = _bundle(self.tmp)
        html = m["report"].read_text(encoding="utf-8")
        self.assertIn("某高校", html)
        self.assertNotIn("某省大学", html)

    def test_declared_redaction_with_leak_rejected(self):
        ed = copy.deepcopy(ED_A)
        ed["redactions"] = [{"from": "某省大学", "to": "某高校"},
                            {"from": "不存在的串", "to": "x"}]
        # 白名单未覆盖的标记泄漏场景：往证据里放一个新标记并声明部分脱敏
        report = copy.deepcopy(REPORT_A)
        report["private_markers"].append("ABC 消费品牌")
        report["evidence"][0]["quote"] = "在 ABC 消费品牌实习期间独立撰写并发布公众号推文 12 篇，平均阅读 800+，最高单篇阅读 4600"
        with self.assertRaises(ValueError) as ctx:
            _bundle(self.tmp, report, ed)
        self.assertIn("ABC 消费品牌", str(ctx.exception))

    def test_no_redactions_report_keeps_material(self):
        """未声明 redactions：完整报告按成员私有件保留材料细节（SKILL 口径：不替用户外发）。"""
        ed = copy.deepcopy(ED_A)
        del ed["redactions"]
        m = red.generate_bundle(copy.deepcopy(REPORT_A), ed, self.tmp)
        html = m["report"].read_text(encoding="utf-8")
        self.assertIn("某省大学", html)

    def test_card_rewrite_diff_also_redacted(self):
        """案例卡改写区默认取报告原文，渲染时同样过白名单（分享面双保险）。"""
        report = copy.deepcopy(REPORT_A)
        marker_in_rw = "某省大学"
        report["rewrites"][0]["original_quote"] = report["rewrites"][0]["original_quote"] + "（某省大学）"
        ed = copy.deepcopy(ED_A)
        m = red.generate_bundle(report, ed, self.tmp)
        rw_html = next(p for p in m["cards"] if "rewrites" in p.name).read_text(encoding="utf-8")
        self.assertIn("某高校", rw_html)


class TestFailureHandling(unittest.TestCase):
    """失败即报错：内容缺失/版本不对/品牌缺失都明确拒绝，不回退旧模板。"""

    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_invalid_editorial_raises_and_writes_nothing(self):
        ed = copy.deepcopy(ED_A)
        ed["verdict"]["prose"] = "进一步提升竞争力"
        with self.assertRaises(ValueError):
            _bundle(self.tmp, ed=ed)
        self.assertFalse((self.tmp / "report.html").exists(), "校验失败不得产出半成品")

    def test_old_editorial_version_rejected_as_default(self):
        ed = copy.deepcopy(ED_A)
        ed["editorial_version"] = "jd-match-editorial/9.9.9"
        with self.assertRaises(ValueError):
            _bundle(self.tmp, ed=ed)

    def test_missing_brand_config_raises(self):
        with self.assertRaises(ValueError):
            red.load_brand(self.tmp / "no-such-brand.json")

    def test_custom_brand_applied(self):
        brand = json.loads((ROOT / "references/brand.json").read_text(encoding="utf-8"))
        brand["search_entry"] = "搜 测试品牌"
        bp = self.tmp / "brand.json"
        bp.write_text(json.dumps(brand, ensure_ascii=False), encoding="utf-8")
        m = red.generate_bundle(copy.deepcopy(REPORT_A), copy.deepcopy(ED_A), self.tmp, brand_path=bp)
        html = m["member_card"].read_text(encoding="utf-8")
        self.assertIn("搜 测试品牌", html)
        acts = next(p for p in m["cards"] if "actions" in p.name).read_text(encoding="utf-8")
        self.assertIn("搜 测试品牌", acts)
        red._BRAND = {}

    def test_main_missing_editorial_file_exit_1(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts/render_editorial.py"),
             "--input", str(ROOT / "examples/case-a-freshgrad-ops/expected.json"),
             "--editorial", str(self.tmp / "nope.json"),
             "--outdir", str(self.tmp / "out")],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("不存在", r.stderr)


class TestT1AcceptedVisualRegression(unittest.TestCase):
    """T1 用户验收的视觉与表达规则移植回归（发布面不得回退）。"""

    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.m = _bundle(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp)

    def _report(self):
        return self.m["report"].read_text(encoding="utf-8")

    def test_report_section3_label(self):
        html = self._report()
        self.assertIn("重点改写区 · 局部精准优化", html)
        self.assertNotIn("Editorial Rewrites", html)

    def test_report_footer_no_internal_version(self):
        html = self._report()
        self.assertIn("求职体检与深度匹配报告 · 编辑部审校定稿", html)
        self.assertNotIn("Editorial Red-Pen", html)
        self.assertNotIn("jd-match-editorial/", html)
        self.assertNotIn("jd-match-voice/", html)

    def test_report_toc_mobile_css(self):
        self.assertIn(".toc-bar{flex-wrap:wrap", self._report())

    def test_report_rewrite_density_css(self):
        html = self._report()
        # 改写卡呼吸感规则在案例卡 CSS；报告侧验证 TOC/页脚/节标签，卡侧单独验证
        self.assertIn(".diff-list{display:flex;flex-direction:column;gap:18px", self.m["cards"][0].read_text(encoding="utf-8"))

    def test_actions_card_brand_box(self):
        acts = next(p for p in self.m["cards"] if "actions" in p.name).read_text(encoding="utf-8")
        self.assertIn("RESUME FIT AUDIT", acts)
        brand = json.loads((ROOT / "references/brand.json").read_text(encoding="utf-8"))
        self.assertIn(brand["search_entry"], acts)
        self.assertIn(brand["cta"], acts)

    def test_action_copy_id_renamed(self):
        html = self._report()
        self.assertIn("copy-act-box-", html)
        self.assertNotIn("copy-src-act-", html)

    def test_social_note_no_version(self):
        social = self.m["social"].read_text(encoding="utf-8")
        self.assertIn("求职内容规范表达标准", social)
        self.assertNotIn("jd-match-voice/", social)

    def test_case_cards_numbering(self):
        names = sorted(p.name for p in self.m["cards"])
        self.assertEqual(names[0], "card-01-cover.html")
        html = self.m["cards"][0].read_text(encoding="utf-8")
        self.assertIn("CARD 01 / 05", html)


class TestNoInternalTokensInUserVisible(unittest.TestCase):
    """用户可见文字不出现内部标记；内部引用只留在数据层。"""

    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.m = _bundle(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp)

    def _visible(self, path):
        text = Path(path).read_text(encoding="utf-8")
        text = re.sub(r"<style[\s\S]*?</style>", "", text)
        text = re.sub(r"<script[\s\S]*?</script>", "", text)
        text = re.sub(r"<!--[\s\S]*?-->", "", text)
        return html_unescape(re.sub(r"<[^>]+>", " ", text))

    def test_report_and_cards_visible_text_clean(self):
        tokens = ["src-resume", "src-jd", "jd-match-report", "jd-match-editorial",
                  "jd-match-rubric", "jd-match-voice", "gate-a1", "req-a1", "ev-a1",
                  "Editorial Red-Pen", "Editorial Rewrites"]
        for f in [self.m["report"], self.m["member_card"], *self.m["cards"]]:
            visible = self._visible(f)
            for tok in tokens:
                self.assertNotIn(tok, visible, f"{f.name} 可见文本泄漏内部标记 {tok}")


def html_unescape(s):
    import html as _h
    return _h.unescape(s)


if __name__ == "__main__":
    unittest.main()
