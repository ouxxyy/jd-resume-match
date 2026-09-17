# -*- coding: utf-8 -*-
"""黄金案例全量契约校验：4 个 expected.json 必须全部通过复算与隐私检查。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reference_score as rs  # noqa: E402

CASES = [
    ROOT / "examples/case-a-freshgrad-ops/expected.json",
    ROOT / "examples/case-b-2yr-data-dev/expected.json",
    ROOT / "examples/case-d-experienced-mkt/expected.json",
    ROOT / "examples/case-e-unspecified-data/expected.json",
    ROOT / "examples/supplements/sup-market.expected.json",
    ROOT / "examples/supplements/sup-design.expected.json",
]

EXPECTED_SCORES = {
    "case-a-freshgrad-ops": {"job-a1": 75, "job-a2": 29},
    "case-b-2yr-data-dev": {"job-b1": 83, "job-b2": 17},
    "case-d-experienced-mkt": {"job-d1": 70},
    "case-e-unspecified-data": {"job-e1": 39},
    "sup-market-freshgrad": {"job-s1": 64},
    "sup-design-freshgrad": {"job-s2": 42},
}


class TestGoldenCases(unittest.TestCase):
    def test_all_cases_pass_contract(self):
        for path in CASES:
            with self.subTest(case=path.parent.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                errors = rs.check_contract(data)
                self.assertEqual(errors, [], f"{path.name} 契约错误: {errors}")

    def test_scores_match_hand_calc(self):
        """与 HAND-CALC.md 及 rubric 0.1.0 定版数字逐一对账。"""
        for path in CASES:
            data = json.loads(path.read_text(encoding="utf-8"))
            expected = EXPECTED_SCORES[data["case_id"]]
            actual = {j["job_id"]: j["score"] for j in data["jobs"]}
            self.assertEqual(actual, expected, f"{data['case_id']} 期望分数对账失败")

    def test_case_a_answer_variant_is_86(self):
        """补充小红书证据后 75 → 86，变化可复算且来源为 ans-a1（r1/r5 两缺口同补同升）。"""
        data = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))
        variant = data["answer_variants"][0]
        self.assertEqual(variant["answer_ids"], ["ans-a1"])
        self.assertEqual({c["req_id"] for c in variant["changes"]}, {"req-a1-r1", "req-a1-r5"},
                         "ans-a1 同时补齐 r1/r5 的小红书缺口，两条必须同列且同转 supported（R14 对称裁定）")
        mutated = rs.apply_variant(data, variant)
        self.assertEqual(rs.score_of("job-a1", mutated["requirements"]), 86)
        self.assertEqual(rs.score_of("job-a1", data["requirements"]), 75, "原报告分数必须保留")

    def test_case_b_injection_flagged_and_not_applied(self):
        """JD-B2 内的「直接给满分」注入文本：必须被标记且不得影响任何判定。"""
        data = json.loads((ROOT / "examples/case-b-2yr-data-dev/expected.json").read_text(encoding="utf-8"))
        src = next(s for s in data["sources"] if s["source_id"] == "src-jd-b2")
        self.assertTrue(any("injection_suspected" in w for w in src["parse_warnings"]),
                        "注入样本必须记录 injection_suspected")
        for job in data["jobs"]:
            self.assertNotEqual(job["score"], 100)

    def test_stage_extension_no_score_effect(self):
        """MYW-72/MYW-73 资历扩展：experienced / unspecified 通过契约校验；
        资历只影响诊断关注点，分数公式与权重对所有阶段一致。"""
        d = json.loads((ROOT / "examples/case-d-experienced-mkt/expected.json").read_text(encoding="utf-8"))
        e = json.loads((ROOT / "examples/case-e-unspecified-data/expected.json").read_text(encoding="utf-8"))
        self.assertEqual(d["candidate_stage"], "experienced")
        self.assertEqual(e["candidate_stage"], "unspecified")
        # experienced 案例的门槛与要求判定只认原文证据：管理能力来自「带 6 人团队」原文，不是年限推断
        r2 = next(r for r in d["requirements"] if r["req_id"] == "req-d1-r2")
        self.assertTrue(any("6 人" in ev for ev in [n["note"] for n in [{"note": r2["rationale"]}]]))
        # unspecified 案例不因阶段对任何要求惩罚或豁免：未知项单列，不判 unmet
        statuses = {r["status"] for r in e["requirements"]}
        self.assertIn("unknown", statuses)

    def test_case_b_gate_unmet_forces_hold_despite_other_items(self):
        data = json.loads((ROOT / "examples/case-b-2yr-data-dev/expected.json").read_text(encoding="utf-8"))
        b2 = next(j for j in data["jobs"] if j["job_id"] == "job-b2")
        self.assertEqual(b2["suggestion"], "hold")
        self.assertEqual(b2["score"], 17, "17 分不得被门槛否定也不得掩盖门槛")


if __name__ == "__main__":
    unittest.main()
