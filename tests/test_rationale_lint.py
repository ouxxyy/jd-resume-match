# -*- coding: utf-8 -*-
"""test_rationale_lint.py — MYW-69 reviewer 顺延修正 b 的回归测试：
「rationale 与 answers 无矛盾」进入重生成检查（validate_report.py 语义层）。
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_report as vr  # noqa: E402

CASE_A = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))


class TestRationaleAnswersConsistency(unittest.TestCase):
    def test_golden_case_a_passes_after_rewording(self):
        """顺延修正 a 落地后（措辞按对照稿口径），Case A 全量校验必须通过。"""
        errors = vr.check_report(CASE_A, schema=None)
        # check_report 需要 schema；走语义层直接验证
        errors = vr.check_semantics(CASE_A)
        rationale_errors = [e for e in errors if "rationale" in e or "answers" in e]
        self.assertEqual(rationale_errors, [], rationale_errors)

    def test_contradictory_rationale_flagged(self):
        """存在适用回答时，rationale 写「均无任何记录」必须被拦截。"""
        data = copy.deepcopy(CASE_A)
        for r in data["requirements"]:
            if r["req_id"] == "req-a1-r1":
                r["rationale"] = "公众号子项有证据；小红书子项简历与回答均无任何记录，判 partial"
        errors = vr.check_semantics(data)
        hits = [e for e in errors if "rationale 与 answers 矛盾" in e]
        self.assertTrue(hits, f"应检出 rationale/answers 矛盾，实际错误: {errors}")

    def test_no_answers_no_false_positive(self):
        """无追问回答的案例不受该检查影响（不误报）。"""
        data = copy.deepcopy(CASE_A)
        data["answers"] = []
        data["answer_variants"] = []
        for r in data["requirements"]:
            if r["req_id"] == "req-a1-r1":
                r["rationale"] = "公众号子项有证据；小红书子项无任何记录，判 partial"
        errors = vr.check_semantics(data)
        hits = [e for e in errors if "rationale 与 answers 矛盾" in e]
        self.assertEqual(hits, [], hits)

    def test_reworded_rationale_uses_copy_redesign_wording(self):
        """顺延修正 a：req-a1-r1 措辞改为对照稿口径（按简历正文算 + 重跑口径），且不再是旧表述。"""
        r1 = next(r for r in CASE_A["requirements"] if r["req_id"] == "req-a1-r1")
        self.assertIn("按简历正文算", r1["rationale"])
        self.assertIn("补充事实", r1["rationale"])
        self.assertNotIn("均无任何记录", r1["rationale"])
        self.assertNotIn("§", r1["rationale"])
        self.assertNotIn("R14", r1["rationale"])
        # 只动措辞，禁动 status/score —— 状态与基线一致
        self.assertEqual(r1["status"], "partial")


if __name__ == "__main__":
    unittest.main()
