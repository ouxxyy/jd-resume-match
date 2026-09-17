# -*- coding: utf-8 -*-
"""test_render_editorial.py — MYW-69 第 4 步「通用生成链路」的契约防护测试。

覆盖：内容引用与事实纪律（引号逐字/数字溯源/职责词零新增）、旧接口兼容
（render_report.py 无 --editorial 行为不变）、脱敏隔离（分享面不泄漏）、
导出回归（卡片 1080×1440 / 预览同 DOM / PNG 导出按钮）、表达纪律（内部话不出机房）。
不删除任何既有评分或隐私断言；黄金案例分数基线由 test_golden_cases.py 继续管辖。
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
import render_report as rr  # noqa: E402

CASES = [
    ("case-a-freshgrad-ops", ROOT / "examples/case-a-freshgrad-ops/expected.json",
     ROOT / "examples/case-a-freshgrad-ops/editorial.json"),
    ("case-b-2yr-data-dev", ROOT / "examples/case-b-2yr-data-dev/expected.json",
     ROOT / "examples/case-b-2yr-data-dev/editorial.json"),
    ("sup-market-freshgrad", ROOT / "examples/supplements/sup-market.expected.json",
     ROOT / "examples/supplements/sup-market.editorial.json"),
    ("sup-design-freshgrad", ROOT / "examples/supplements/sup-design.expected.json",
     ROOT / "examples/supplements/sup-design.editorial.json"),
]

REPORTS = {name: json.loads(rep.read_text(encoding="utf-8")) for name, rep, _ in CASES}
EDS = {name: json.loads(ed.read_text(encoding="utf-8")) for name, _, ed in CASES}


class TestGoldenEditorialContract(unittest.TestCase):
    """四组黄金案例的内容编排必须通过全量契约校验。"""

    def test_all_golden_editorials_validate(self):
        for name, report, ed in ((n, REPORTS[n], EDS[n]) for n, _, _ in CASES):
            errors = red.validate_editorial(report, ed)
            self.assertEqual(errors, [], f"{name} 内容编排校验失败: {errors}")

    def test_editorial_version_is_independent(self):
        """内容编排独立带版本，不碰评分报告 JSON / rubric 版本。
        case-a 已升 0.2.0（成员版默认链路的示范夹具）；其余保留 0.1.0 作读取兼容活夹具。"""
        for name, _, _ in CASES:
            self.assertIn(EDS[name]["editorial_version"],
                          ("jd-match-editorial/0.1.0", "jd-match-editorial/0.2.0"))
            self.assertEqual(EDS[name]["voice_version"], "jd-match-voice/0.2.0")
            self.assertEqual(REPORTS[name]["schema_version"], "jd-match-report/0.1.0")
            self.assertEqual(REPORTS[name]["rubric_version"], "jd-match-rubric/0.1.0")

    def test_editorial_forbids_score_keys(self):
        """编排层永不携带分数：分数只能来自报告 JSON（渲染器无算分权）。"""
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["verdict"]["score"] = 99
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("score" in e for e in errors), errors)

    def test_case_id_mismatch_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["case_id"] = "other-case"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("case_id" in e for e in errors), errors)

    def test_job_must_be_primary(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["job_id"] = "job-a2"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("主目标" in e for e in errors), errors)


class TestContentReferenceIntegrity(unittest.TestCase):
    """内容引用：ID 可解析、引号逐字、数字溯源、职责词零新增。"""

    def test_loupe_raw_must_be_verbatim_evidence_slice(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["findings"][0]["loupe"]["raw_line"] = "实习写了 12 篇推文，最高 4600 阅读"  # 转述而非逐字
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("raw_line" in e for e in errors), errors)

    def test_jd_anchor_must_be_verbatim_jd_quote(self):
        """reviewer 顺延修正 b：引号内一律 JD 原文，转述被拒。"""
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["rewrites"][0]["jd_anchor"] = "会用 Figma/Axure 画原型"  # 不属于该要求
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("jd_anchor" in e for e in errors), errors)

    def test_after_text_number_must_trace_back(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["rewrites"][0]["after_text"] = "运营 2 个共约 500 人的用户社群，策划社群抽奖活动 1 场，参与率约 25%"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("500" in e and "数字" in e for e in errors), errors)

    def test_after_text_scope_word_addition_rejected(self):
        """借润色加「独立/主导」类职责 = 埋雷，校验必须拦下。"""
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["rewrites"][0]["after_text"] = "独立运营 2 个共约 400 人的用户社群，策划社群抽奖活动 1 场，参与率约 25%"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("独立" in e and "职责范围词" in e for e in errors), errors)

    def test_social_title_untraceable_number_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["social"]["titles"][0]["text"] = "改了 3 个句子，匹配分 75→95"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("95" in e for e in errors), errors)

    def test_missing_requirement_note_rejected(self):
        """证据详情必须全量人话覆盖：缺注解不能回退渲染内部口径。"""
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["evidence_notes"] = data["evidence_notes"][:-1]
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("evidence_notes 缺少" in e for e in errors), errors)

    def test_missing_secondary_note_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["secondary_notes"] = data["secondary_notes"][:-1]
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("secondary_notes 缺少" in e for e in errors), errors)

    def test_social_must_note_synthetic(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["social"]["body_md"] = data["social"]["body_md"].replace("合成案例", "真实案例")
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("合成案例" in e for e in errors), errors)

    def test_titles_must_be_exactly_three_with_basis(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["social"]["titles"] = data["social"]["titles"][:2]
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("3 条备选" in e for e in errors), errors)


class TestVoiceDiscipline(unittest.TestCase):
    """内部话不出机房：机器标识、状态机词、规则引用禁入用户可见文案。"""

    def test_internal_id_in_user_text_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["verdict"]["prose"] = "按 gate-a1-g2 先核实再投"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("内部机器标识" in e for e in errors), errors)

    def test_status_word_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["evidence_notes"][0]["note"] = "两个子项仅一个有证据，记 partial"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("状态机英文词" in e for e in errors), errors)

    def test_rubric_reference_rejected(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["findings"][0]["body"] = "按决策表第 2 条，先核实再投"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("规则引用" in e for e in errors), errors)

    def test_generated_outputs_contain_no_internal_ids(self):
        for name, _, _ in CASES:
            report_html = red.render_editorial_report(REPORTS[name], EDS[name])
            cards = red.render_cards(REPORTS[name], EDS[name])
            social = red.render_social_md(REPORTS[name], EDS[name])
            for blob_name, blob in [("report", report_html), ("social", social)] + \
                    [(f"card {fn}", ch) for fn, ch in cards]:
                # 只扫用户可见文本：剥掉样式/脚本块与标签属性（class="job-tabs" 是 CSS 类名不是泄漏）
                visible = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", blob, flags=re.S)
                visible = re.sub(r"<[^>]+>", " ", visible)
                for m in red.INTERNAL_ID_RE.finditer(visible):
                    self.fail(f"{name} {blob_name} 泄漏内部标识 {m.group(0)}")


class TestPrivacyIsolation(unittest.TestCase):
    """脱敏隔离：分享面（卡片 + 发布文案）不得出现私密标记/邮箱/手机号。"""

    PRIVACY_TARGETS = ["李晓晓", "13800001234", "lixiaoxiao@example.com", "王成", "13900005678"]

    def test_share_outputs_clean(self):
        for name, _, _ in CASES:
            markers = REPORTS[name]["private_markers"]
            cards = red.render_cards(REPORTS[name], EDS[name])
            social = red.render_social_md(REPORTS[name], EDS[name])
            preview = red.render_cards_preview(REPORTS[name], EDS[name], cards)
            for blob_name, blob in [("social", social), ("preview", preview)] + \
                    [(f"card {fn}", ch) for fn, ch in cards]:
                for marker in markers:
                    self.assertNotIn(marker, blob, f"{name} {blob_name} 泄漏私密标记 {marker}")
                self.assertIsNone(red.EMAIL_RE.search(blob), f"{name} {blob_name} 疑似邮箱")
                self.assertIsNone(red.PHONE_RE.search(blob), f"{name} {blob_name} 疑似手机号")

    def test_privacy_lint_catches_marker_in_editorial(self):
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["findings"][0]["body"] = "李晓晓的 4600 爆款被埋了"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        self.assertTrue(any("私密标记" in e for e in errors), errors)

    def test_share_card_does_not_embed_full_evidence_dump(self):
        """卡片只吃编排白名单内容：不内嵌完整证据 JSON（与 build_share 白名单同向）。"""
        for name, _, _ in CASES:
            cards = red.render_cards(REPORTS[name], EDS[name])
            for fn, ch in cards:
                self.assertNotIn("__REPORT_DATA_JSON__", ch)
                self.assertNotIn("answer_variants", ch)


class TestOldInterfaceCompatibility(unittest.TestCase):
    """旧接口兼容：不带 --editorial 的 render_report 行为不变；带 --editorial 走新链路。"""

    def test_render_report_without_editorial_unchanged(self):
        html_a = rr.render_report(REPORTS["case-a-freshgrad-ops"])
        self.assertIn("求职体检单", html_a)  # 旧模板特征
        html_b = rr.render_report(REPORTS["case-b-2yr-data-dev"])
        self.assertIn("数据分析师", html_b)
        self.assertIn("建议暂缓投递", html_b)

    def test_editorial_report_renders_editorial_style(self):
        html = red.render_editorial_report(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"])
        self.assertIn("RESUME EDITORIAL AUDIT", html)
        self.assertIn("编辑部审校定稿", html)
        self.assertIn("能投，但先改三处再投", html)
        self.assertNotIn("求职体检单", html)  # 不是旧模板

    def test_report_embeds_scores_from_report_json_only(self):
        """渲染器无算分权：报告里出现的分数必须来自报告 JSON。"""
        html = red.render_editorial_report(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"])
        self.assertIn(">75<", html.replace('">75</div>', ">75<"))  # 分数区 75
        self.assertIn("能投，但先改三处再投", html)
        # 篡改编排不改变分数来源：分数不在编排里（已由 score 禁令测试覆盖）

    def test_no_editorial_data_no_publish_assets(self):
        """宁缺毋滥：没有内容编排数据时，不产爆款标题、不拼卡片（旧入口照常出报告）。"""
        html = rr.render_report(REPORTS["case-a-freshgrad-ops"])
        self.assertIsInstance(html, str)  # 旧报告照常
        self.assertNotIn("备选标题", html)  # 不凭空生成发布素材
        self.assertNotIn("RESUME EDITORIAL AUDIT", html)


class TestExportRegression(unittest.TestCase):
    """导出回归：卡片 1080×1440 固定画布；预览与导出共用同一卡片 DOM。"""

    def test_cards_have_fixed_1080_1440_canvas(self):
        for name, _, _ in CASES:
            for fn, ch in red.render_cards(REPORTS[name], EDS[name]):
                self.assertIn("width:1080px;height:1440px", ch.replace(" ", ""), f"{name} {fn}")
                self.assertIn("CARD ", ch)

    def test_card_count_within_contract(self):
        """4–6 张契约：A/B 各 5 张；补充案例有效改写仅 1 处，按宁缺毋滥减为 4 张。"""
        counts = {}
        for name, _, _ in CASES:
            counts[name] = len(red.render_cards(REPORTS[name], EDS[name]))
        self.assertEqual(counts["case-a-freshgrad-ops"], 5)
        self.assertEqual(counts["case-b-2yr-data-dev"], 5)
        self.assertEqual(counts["sup-market-freshgrad"], 4)
        self.assertEqual(counts["sup-design-freshgrad"], 4)
        for name, n in counts.items():
            self.assertTrue(4 <= n <= 6, f"{name} 卡片数 {n} 超出 4–6 契约")

    def test_preview_inlines_same_card_dom_for_export(self):
        """预览与 PNG 导出共用同一排版实现：预览内联卡片 DOM + foreignObject 导出。"""
        for name, _, _ in CASES:
            cards = red.render_cards(REPORTS[name], EDS[name])
            preview = red.render_cards_preview(REPORTS[name], EDS[name], cards)
            self.assertIn('id="cardCss"', preview)          # 同一份卡片样式
            self.assertIn("foreignObject", preview)         # DOM → PNG（非另画 Canvas）
            self.assertIn("btnExportAll", preview)
            dom_part = preview.split("<script>", 1)[0]      # 导出脚本里也引用该选择器，只数 DOM
            self.assertEqual(len(re.findall(r'data-export="card-\d+"', dom_part)), len(cards))
            for _, ch in cards:  # 预览里的卡片内容与单卡文件同源
                body_probe = re.search(r'<div class="main-headline">(.*?)</h1>', ch, re.S)
                if body_probe:
                    self.assertIn(body_probe.group(1)[:40], preview)

    def test_preview_has_no_external_resources(self):
        cards = red.render_cards(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"])
        preview = red.render_cards_preview(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"], cards)
        for pat in ('<script src="http', '<link href="http', '<img src="http'):
            self.assertNotIn(pat, preview)
        for fn, ch in cards:
            for pat in ('<script src="http', '<link href="http', '<img src="http'):
                self.assertNotIn(pat, ch)

    def test_social_md_structure(self):
        md = red.render_social_md(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"])
        self.assertIn("备选标题", md)
        self.assertEqual(md.count("依据："), 3)
        self.assertIn("合成案例", md)
        self.assertIn("发布正文", md)

    def test_social_md_disclaimer_not_duplicated(self):
        """正文自带免责尾注时渲染器不重复追加（Case C 迁移材料踩过的坑）。"""
        c = ROOT / "examples/case-c-2yr-brand-mkt"
        report = json.loads((c / "expected.json").read_text(encoding="utf-8"))
        ed = json.loads((c / "editorial.json").read_text(encoding="utf-8"))
        md = red.render_social_md(report, ed)
        self.assertEqual(md.count("不代表能力或录取概率"), 1, "免责尾注出现两次")

    def test_social_md_note_format_is_finalized_style(self):
        """尾注定稿口径：note 非空 → 空行分隔 + 末尾换行（与 docs/mockup/social-post.md 一致）。"""
        report, ed = REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"]
        md = red.render_social_md(report, ed)
        note = ed["social"]["synthetic_note"]
        self.assertTrue(md.endswith(note + "\n"), "文件应以尾注 + 末尾换行收束")
        self.assertIn(f"事实。\n\n{note}", md, "尾注与正文之间必须空行分隔")
        # 去重路径（note 命中去重）→ 仅正文末换行，格式同样收束
        c = ROOT / "examples/case-c-2yr-brand-mkt"
        report_c = json.loads((c / "expected.json").read_text(encoding="utf-8"))
        ed_c = json.loads((c / "editorial.json").read_text(encoding="utf-8"))
        md_c = red.render_social_md(report_c, ed_c)
        self.assertTrue(md_c.endswith("\n"), "去重路径输出应有末尾换行")

    def test_synthetic_note_privacy_lint_rejects_marker(self):
        """编排自定义尾注上分享面：夹带私密标记必须被拒（reviewer 观察项 1 收口）。"""
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["social"]["synthetic_note"] = "（分数仅供参考；联系方式：李晓晓 13800001234）"
        errors = red.validate_editorial(REPORTS["case-a-freshgrad-ops"], data)
        hits = [e for e in errors if "synthetic_note" in e and ("私密标记" in e or "邮箱" in e or "手机号" in e)]
        self.assertTrue(hits, f"应检出 synthetic_note 夹带私密内容，实际错误: {errors}")


class TestBundleGeneration(unittest.TestCase):
    """generate_bundle 落盘与校验失败拒绝。"""

    def test_bundle_writes_all_assets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "case-a"
            manifest = red.generate_bundle(REPORTS["case-a-freshgrad-ops"], EDS["case-a-freshgrad-ops"], outdir)
            self.assertTrue(manifest["report"].exists())
            self.assertTrue(manifest["preview"].exists())
            self.assertTrue(manifest["social"].exists())
            self.assertEqual(len(manifest["cards"]), 5)
            for p in manifest["cards"]:
                self.assertTrue(p.exists())

    def test_bundle_rejects_invalid_editorial(self):
        import tempfile
        data = copy.deepcopy(EDS["case-a-freshgrad-ops"])
        data["rewrites"][0]["after_text"] = "独立运营 2 个共约 900 人的用户社群"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                red.generate_bundle(REPORTS["case-a-freshgrad-ops"], data, Path(td) / "x")


if __name__ == "__main__":
    unittest.main()
