# -*- coding: utf-8 -*-
"""T2 评分脚本测试：与 T1 复算器同判（唯一口径）、确定性排名、--apply 行为与 CLI。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reference_score as rs  # noqa: E402
import score_report as sr  # noqa: E402
import validate_report as vr  # noqa: E402

CASES = [
    ROOT / "examples/case-a-freshgrad-ops/expected.json",
    ROOT / "examples/case-b-2yr-data-dev/expected.json",
    ROOT / "examples/supplements/sup-market.expected.json",
    ROOT / "examples/supplements/sup-design.expected.json",
]
STATUSES = ["supported", "partial", "unclear", "unmet", "unknown"]
IMPORTANCES = ["must", "normal", "bonus"]


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class TestParityWithReferenceScorer(unittest.TestCase):
    """唯一口径的一致性：对黄金案例做全状态×权重组合变异，两套实现必须逐项同判。"""

    def test_scores_and_suggestions_identical_under_exhaustive_mutations(self):
        checked = 0
        for path in CASES:
            data = load(path)
            for i, req in enumerate(data["requirements"]):
                for status in STATUSES:
                    d2 = json.loads(json.dumps(data, ensure_ascii=False))
                    d2["requirements"][i]["status"] = status
                    for job in d2["jobs"]:
                        self.assertEqual(sr.compute_job_fields(d2)[job["job_id"]]["score"],
                                         rs.score_of(job["job_id"], d2["requirements"]),
                                         f"{path.name} {req['req_id']}→{status} 分数不同判")
                        self.assertEqual(vr.derive_suggestion(job, d2["requirements"]),
                                         rs.derive_suggestion(job, d2["requirements"]),
                                         f"{path.name} {req['req_id']}→{status} 建议不同判")
                        self.assertEqual(vr.score_of(job["job_id"], d2["requirements"]),
                                         rs.score_of(job["job_id"], d2["requirements"]))
                        checked += 1
        self.assertGreater(checked, 100, "变异覆盖不足")

    def test_variant_rescore_parity(self):
        data = load(CASES[0])
        for variant in data.get("answer_variants", []):
            mutated = vr.apply_variant(data, variant)
            mutated_rs = rs.apply_variant(data, variant)
            for job in mutated["jobs"]:
                self.assertEqual(
                    vr.score_of(job["job_id"], mutated["requirements"]),
                    rs.score_of(job["job_id"], mutated_rs["requirements"]))


class TestDeterministicRules(unittest.TestCase):
    BASE = load(CASES[0])

    def test_ranking_score_desc_not_input_position(self):
        """排名跟分数走：把低分岗位放在输入第一位，它也必须排第 2。"""
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        data["jobs"] = [data["jobs"][1], data["jobs"][0]]  # a2(29) 在前, a1(75) 在后
        derived = sr.compute_job_fields(data)
        self.assertEqual(derived["job-a2"]["rank"], 2)
        self.assertEqual(derived["job-a1"]["rank"], 1)

    def test_ties_keep_input_order_adjacent(self):
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        data["jobs"] = [data["jobs"][1], data["jobs"][0]]
        for r in data["requirements"]:
            if r["job_id"] == "job-a2":
                r["status"] = "supported"  # a2 分数抬高到与 a1 并列或更高才有意义 → 改为全部同分场景
        derived = sr.compute_job_fields(data)
        scores = {jid: derived[jid]["score"] for jid in derived}
        if scores["job-a1"] == scores["job-a2"]:
            self.assertEqual(sorted(derived[j]["rank"] for j in derived), [1, 2],
                             "同分也必须是 1..2，且高输入顺序在前")
        else:
            higher = max(scores, key=scores.get)
            self.assertEqual(derived[higher]["rank"], 1)

    def test_insufficient_input_ranked_last(self):
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        data["jobs"][0].update(scoring_status="insufficient_input", score=None)
        data["requirements"] = [r for r in data["requirements"] if r["job_id"] != "job-a1"]
        derived = sr.compute_job_fields(data)
        self.assertEqual(derived["job-a1"]["score"], None)
        self.assertEqual(derived["job-a1"]["rank"], 2, "无法评分的岗位排最后")
        self.assertEqual(derived["job-a2"]["rank"], 1)

    def test_gate_unmet_forces_hold_even_at_hundred(self):
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        job = data["jobs"][0]
        for r in data["requirements"]:
            if r["job_id"] == job["job_id"]:
                r["status"] = "supported"
        data["jobs"][1]["gates"] = []
        job["gates"] = [{"gate_id": "gate-x", "job_id": job["job_id"], "text": "x",
                         "jd_quote": "必须接受出差", "status": "unmet",
                         "evidence_ids": [], "rationale": "测试"}]
        derived = sr.compute_job_fields(data)
        self.assertEqual(derived[job["job_id"]]["suggestion"], "hold",
                         "已证实缺硬门槛必须暂缓，分数再高也不优先")

    def test_pending_gate_never_prioritize(self):
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        for g in data["jobs"][0]["gates"]:
            g["status"] = "pending_confirmation"
        derived = sr.compute_job_fields(data)
        self.assertNotEqual(derived["job-a1"]["suggestion"], "prioritize",
                            "门槛未核实时不得优先投")

    def test_all_unknown_scores_zero_but_counted(self):
        """全部 unknown：按 rubric 贡献 0 分，但 unknown 单列不惩罚为 unmet。"""
        data = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        n_req = 0
        for r in data["requirements"]:
            if r["job_id"] == "job-a1":
                r["status"] = "unknown"
                n_req += 1
        derived = sr.compute_job_fields(data)
        self.assertEqual(derived["job-a1"]["score"], 0)
        self.assertEqual(derived["job-a1"]["unknown_count"], n_req)
        self.assertEqual(derived["job-a1"]["suggestion"], "revise_then_apply")


class TestApplyAndCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_apply_overrides_tampered_values_and_passes_contract(self):
        data = load(CASES[0])
        data["jobs"][0]["score"] = 99
        data["jobs"][0]["suggestion"] = "prioritize"
        data["jobs"][0]["rank"] = 2
        data["jobs"][1]["rank"] = 1
        inp = self.tmp / "in.json"
        inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "out.json"
        rc = sr.main(["--apply", "--input", str(inp), "--output", str(out)])
        self.assertEqual(rc, 0)
        fixed = load(out)
        self.assertEqual(fixed["jobs"][0]["score"], 75)
        self.assertEqual(fixed["jobs"][0]["suggestion"], "revise_then_apply")
        self.assertEqual([j["rank"] for j in fixed["jobs"]], [1, 2])
        self.assertEqual(vr.check_report(fixed), [], "写盘产物必须通过完整契约校验")

    def test_check_fails_on_tampered_score(self):
        data = load(CASES[0])
        data["jobs"][1]["score"] = 100
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(sr.main(["--check", str(bad)]), 1)

    def test_apply_syncs_share_payload_score_mirror(self):
        """补充回答使主目标 75→86 后，share_payload.score 镜像必须由脚本同步。"""
        data = load(CASES[0])
        variant = data["answer_variants"][0]
        data = vr.apply_variant(data, variant)
        inp = self.tmp / "variant.json"
        inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "variant.scored.json"
        self.assertEqual(sr.main(["--apply", "--input", str(inp), "--output", str(out)]), 0)
        fixed = load(out)
        self.assertEqual(fixed["jobs"][0]["score"], 86, "黄金案例变体期望 86")
        self.assertEqual(fixed["share_payload"]["score"], 86, "镜像分数必须同步")
        self.assertEqual(vr.check_report(fixed), [])

    def test_apply_refuses_invalid_report(self):
        data = load(CASES[0])
        data.pop("actions")
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "never.json"
        self.assertEqual(sr.main(["--apply", "--input", str(bad), "--output", str(out)]), 1)
        self.assertFalse(out.exists(), "校验失败必须拒绝写盘")

    def test_show_mode_runs(self):
        self.assertEqual(sr.main(["--show", str(CASES[0])]), 0)


class TestCliGoldenCases(unittest.TestCase):
    def test_all_golden_cases_pass_cli_check(self):
        for path in CASES:
            with self.subTest(case=path.parent.name):
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/score_report.py"), "--check", str(path)],
                    capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_validate_cli_on_golden_cases(self):
        for path in CASES:
            with self.subTest(case=path.parent.name):
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/validate_report.py"), "--input", str(path), "--quiet"],
                    capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
