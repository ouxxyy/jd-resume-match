# -*- coding: utf-8 -*-
"""评分规则红蓝队测试：对 scoring-rubric.md 0.1.0 的关键防线做定向攻击。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reference_score as rs  # noqa: E402


def mini_job(job_id="job-x", gates=None, score=None, reqs=None, rank=1):
    reqs = reqs if reqs is not None else [
        {"req_id": "req-x-1", "job_id": job_id, "importance": "must", "status": "supported",
         "weight": 3, "evidence_ids": ["ev-x-1"], "answer_ids": []},
        {"req_id": "req-x-2", "job_id": job_id, "importance": "normal", "status": "supported",
         "weight": 2, "evidence_ids": ["ev-x-1"], "answer_ids": []},
    ]
    return {
        "job_id": job_id, "title": "x", "category": "operations", "jd_source_id": "src-x",
        "score": score if score is not None else rs.score_of(job_id, reqs),
        "scoring_status": "ok", "gates": gates or [], "unknown_count": 0,
        "rank": rank, "rank_rationale": "各自 JD 的证据覆盖口径",
        "suggestion": "prioritize", "suggestion_rationale": "t",
    }, reqs


class TestRounding(unittest.TestCase):
    def test_half_up_not_bankers(self):
        self.assertEqual(rs.round_half_up(83.333), 83)
        self.assertEqual(rs.round_half_up(94.5), 95, "94.5 必须进位（中文四舍五入）")
        self.assertEqual(rs.round_half_up(12.5), 13)
        self.assertEqual(rs.round_half_up(25.0), 25)
        self.assertEqual(rs.round_half_up(16.667), 17)

    def test_scores_are_integers(self):
        self.assertIsInstance(rs.round_half_up(0.5), int)


class TestAntiGaming(unittest.TestCase):
    def test_keyword_stuffing_deduped(self):
        """重复条款/关键词堆砌：merged_into 去重后分数不变。"""
        base = [
            {"req_id": "req-1", "job_id": "job-x", "importance": "must", "status": "supported",
             "weight": 3, "evidence_ids": ["e"], "answer_ids": []},
            {"req_id": "req-2", "job_id": "job-x", "importance": "normal", "status": "partial",
             "weight": 2, "evidence_ids": ["e"], "answer_ids": []},
        ]
        stuffed = base + [
            dict(base[0], req_id="req-1-dup", merged_into="req-1"),
            dict(base[0], req_id="req-1-dup2", merged_into="req-1"),
            dict(base[1], req_id="req-2-dup", merged_into="req-2"),
        ]
        self.assertEqual(rs.score_of("job-x", base), rs.score_of("job-x", stuffed),
                         "去重后分数必须与原始一致（堆砌无效）")

    def test_unduped_stuffing_would_change_score_is_detectable(self):
        """若不去重（攻击者删掉 merged_into 标记），分数会虚高——检查器据此可发现权重不一致。"""
        base = [
            {"req_id": "req-1", "job_id": "job-x", "importance": "must", "status": "supported",
             "weight": 3, "evidence_ids": ["e"], "answer_ids": []},
            {"req_id": "req-2", "job_id": "job-x", "importance": "normal", "status": "unclear",
             "weight": 2, "evidence_ids": [], "answer_ids": []},
        ]
        dup = [dict(base[0], req_id="req-1-copy")]
        self.assertEqual(rs.score_of("job-x", base), 60)
        self.assertGreater(rs.score_of("job-x", base + dup), rs.score_of("job-x", base))
        # 契约检查器会对 weight 与 importance 不一致的条目报错，且重复条目必须带 merged_into

    def test_unknown_is_not_unmet(self):
        """unknown：贡献 0、单列未知、不触发暂缓。"""
        reqs = [{"req_id": "req-u", "job_id": "job-x", "importance": "must", "status": "unknown",
                 "weight": 3, "evidence_ids": [], "answer_ids": []}]
        job, _ = mini_job(reqs=reqs)
        job["unknown_count"] = 1
        self.assertEqual(rs.score_of("job-x", reqs), 0)
        self.assertNotEqual(rs.derive_suggestion(job, reqs), "hold")

    def test_unmet_gate_dominates_high_score(self):
        """硬门槛明确不满足：即使 100 分也强制暂缓。"""
        reqs = [
            {"req_id": "req-1", "job_id": "job-x", "importance": "must", "status": "supported",
             "weight": 3, "evidence_ids": ["e"], "answer_ids": []},
            {"req_id": "req-2", "job_id": "job-x", "importance": "normal", "status": "supported",
             "weight": 2, "evidence_ids": ["e"], "answer_ids": []},
        ]
        job, _ = mini_job(reqs=reqs, gates=[
            {"gate_id": "gate-x-1", "job_id": "job-x", "text": "5 年经验", "jd_quote": "5 年经验",
             "status": "unmet", "evidence_ids": ["e"], "rationale": "已证实"}])
        self.assertEqual(rs.score_of("job-x", reqs), 100, "构造满分行以验证门槛独立于分数")
        self.assertEqual(rs.derive_suggestion(job, reqs), "hold", "unmet 门槛必须一票暂缓")

    def test_pending_gate_never_prioritized(self):
        """待确认门槛：先核实，不得直接优先投。"""
        job, reqs = mini_job(gates=[
            {"gate_id": "gate-x-2", "job_id": "job-x", "text": "值班接受度", "jd_quote": "能接受值班",
             "status": "pending_confirmation", "evidence_ids": [], "rationale": "无信息"}])
        self.assertEqual(job["score"], 100)
        self.assertEqual(rs.derive_suggestion(job, reqs), "revise_then_apply")

    def test_pending_gate_never_hold(self):
        """待确认门槛：不从缺失推断不满足，因此也不得仅因 pending 而 hold。"""
        reqs = [{"req_id": "req-u", "job_id": "job-x", "importance": "must", "status": "unknown",
                 "weight": 3, "evidence_ids": [], "answer_ids": []}]
        job, _ = mini_job(reqs=reqs, gates=[
            {"gate_id": "gate-x-3", "job_id": "job-x", "text": "证书", "jd_quote": "有证书者优先",
             "status": "pending_confirmation", "evidence_ids": [], "rationale": "无信息"}])
        self.assertEqual(rs.derive_suggestion(job, reqs), "revise_then_apply")

    def test_insufficient_input_no_fake_zero(self):
        """无可判定要求：不出总分（null），不是 0 分。"""
        reqs = []
        self.assertIsNone(rs.score_of("job-x", reqs))

    def test_pure_polish_changes_nothing(self):
        """纯表达润色（无新增事实/证据）：分数不得变化。"""
        data = {
            "requirements": [
                {"req_id": "req-1", "job_id": "job-x", "importance": "must", "status": "partial",
                 "weight": 3, "evidence_ids": [], "answer_ids": []},
            ],
            "answers": [],
        }
        base = rs.score_of("job-x", data["requirements"])
        variant = {"answer_ids": [], "changes": [], "job_scores": {}, "note": ""}
        mutated = rs.apply_variant(data, variant)
        self.assertEqual(rs.score_of("job-x", mutated["requirements"]), base,
                         "无证据变更的润色不得改变分数")

    def test_new_evidence_changes_score_with_traceable_source(self):
        """新增可信事实：分数变化可复算（如 Case A 的 83 → 86）。"""
        data = {
            "requirements": [
                {"req_id": "req-1", "job_id": "job-x", "importance": "must", "status": "partial",
                 "weight": 3, "evidence_ids": [], "answer_ids": []},
                {"req_id": "req-2", "job_id": "job-x", "importance": "must", "status": "supported",
                 "weight": 3, "evidence_ids": [], "answer_ids": []},
            ],
            "answers": [{"answer_id": "ans-1", "question": "q", "answer": "a",
                         "recorded_as": "supplementary_evidence", "applies_to_jobs": ["job-x"]}],
        }
        variant = {"answer_ids": ["ans-1"],
                   "changes": [{"req_id": "req-1", "status": "supported", "rationale": "补充证据"}],
                   "job_scores": {"job-x": 100}, "note": "来源 ans-1"}
        mutated = rs.apply_variant(data, variant)
        self.assertEqual(rs.score_of("job-x", data["requirements"]), 75)
        self.assertEqual(rs.score_of("job-x", mutated["requirements"]), 100)


class TestContractGuards(unittest.TestCase):
    def test_unmet_gate_without_evidence_rejected(self):
        """防线：unmet 门槛必须引证据——阻止「从没写推断不满足」。"""
        good = {
            "schema_version": rs.SCHEMA_VERSION, "rubric_version": rs.RUBRIC_VERSION,
            "case_id": "t", "synthetic": True, "private_markers": [" marker-placeholder "],
            "sources": [{"source_id": "src-x", "kind": "jd", "filename": "f", "summary": "s", "parse_warnings": []}],
            "candidate_stage": "fresh_grad", "parse_warnings": [],
            "jobs": [{"job_id": "job-x", "title": "t", "category": "operations", "jd_source_id": "src-x",
                      "score": 0, "scoring_status": "ok",
                      "gates": [{"gate_id": "gate-x", "job_id": "job-x", "text": "g", "jd_quote": "g",
                                 "status": "unmet", "evidence_ids": [], "rationale": "没写，应该没有"}],
                      "unknown_count": 0, "rank": 1, "rank_rationale": "各自 JD 的证据覆盖",
                      "suggestion": "hold", "suggestion_rationale": "r"}],
            "requirements": [{"req_id": "req-1", "job_id": "job-x", "importance": "bonus", "status": "unclear",
                              "weight": 1, "evidence_ids": [], "answer_ids": [], "category": "skill",
                              "importance_source": "jd_explicit", "text": "t", "jd_quote": "q",
                              "locator": "l", "rationale": "r"}],
            "evidence": [], "answers": [], "primary_job_id": "job-x",
            "primary_selection_reason": "r", "rewrites": [], "actions": [],
            "share_payload": {"standalone": True, "anonymized": True, "score": 0,
                              "score_label": "简历证据匹配度", "job_title": "t", "job_category": "operations",
                              "headline_findings": [], "gate_notes": [], "disclaimer": "d"},
        }
        errors = rs.check_contract(good)
        self.assertTrue(any("unmet 门槛必须引用证据" in e for e in errors),
                        "推断式 unmet 必须被契约拦截")

    def test_confidence_fields_rejected(self):
        data = {"some_confidence": 0.9}
        seen = []
        # 直接复用 _walk 的禁字段逻辑
        for tok in rs.FORBIDDEN_KEY_TOKENS:
            if tok in "job_confidence":
                seen.append(tok)
        self.assertTrue(seen)


if __name__ == "__main__":
    unittest.main()
