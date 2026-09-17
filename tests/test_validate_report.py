# -*- coding: utf-8 -*-
"""T2 契约校验测试：结构（schema 子集）+ 语义（引用/决策表/隐私/伪精度）。

策略：以黄金案例为底本做单一变异，断言每类违规都被拦截；同时固定
MYW-58 发现的 schema 内部矛盾的处置方式（private_markers minLength）。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_report as vr  # noqa: E402

BASE = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))


def mutate(fn):
    data = json.loads(json.dumps(BASE, ensure_ascii=False))
    fn(data)
    return data


class TestGoldenPass(unittest.TestCase):
    def test_all_golden_cases_pass(self):
        for rel in ("examples/case-a-freshgrad-ops/expected.json",
                    "examples/case-b-2yr-data-dev/expected.json",
                    "examples/supplements/sup-market.expected.json",
                    "examples/supplements/sup-design.expected.json"):
            data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            self.assertEqual(vr.check_report(data), [], rel)

    def test_private_markers_minlength_deviation_is_self_healing(self):
        """MYW-58 契约偏差必须显式且自愈：仅当文件仍为缺陷值 4 时按 1 执行。"""
        raw = json.loads(vr.SCHEMA_PATH.read_text(encoding="utf-8"))
        file_value = raw["properties"]["private_markers"]["items"].get("minLength")
        schema = vr.load_schema()
        applied = schema["properties"]["private_markers"]["items"].get("minLength")
        if file_value == 4:
            self.assertEqual(applied, 1, "缺陷值 4 与黄金案例（李晓晓/王成）矛盾，必须覆盖为 1")
            self.assertIn("deviation_note", schema["properties"]["private_markers"])
        else:
            self.assertEqual(applied, file_value, "schema 已修订，覆盖必须自动失效")


class TestStructureViolations(unittest.TestCase):
    def test_missing_required_field(self):
        def m(d):
            d.pop("answers")
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("answers" in e for e in errs), errs)

    def test_unknown_top_level_key_rejected(self):
        def m(d):
            d["score_gain"] = "改写后提升 5 分"
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("score_gain" in e for e in errs), "纯润色宣称提分的字段必须被结构层拒绝")

    def test_confidence_key_rejected(self):
        def m(d):
            d["jobs"][0]["confidence"] = 0.92
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("confidence" in e or "置信" in e for e in errs), errs)

    def test_float_score_rejected(self):
        def m(d):
            d["jobs"][0]["score"] = 83.0
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("整数" in e or "integer" in e for e in errs), errs)

    def test_non_dict_top_level(self):
        self.assertTrue(vr.check_report([1, 2]))


class TestSemanticViolations(unittest.TestCase):
    def test_supported_without_citation(self):
        def m(d):
            d["requirements"][0]["evidence_ids"] = []
            d["requirements"][0]["answer_ids"] = []
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("supported/partial 必须引用" in e for e in errs), errs)

    def test_unmet_gate_without_evidence(self):
        def m(d):
            d["jobs"][1]["gates"] = [{"gate_id": "gate-x", "job_id": d["jobs"][1]["job_id"],
                                      "text": "3 年经验", "jd_quote": "3年以上经验",
                                      "status": "unmet", "rationale": "简历没写年限"}]
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("unmet 门槛必须引用证据" in e for e in errs),
                        "从「没写」推断 unmet 必须被拦截")

    def test_met_gate_without_evidence(self):
        """防线：met 门槛必须引证据——rubric §4 定义 met 为「有证据满足」（MYW-62）。"""
        def met_gate(d):
            return {"gate_id": "gate-y", "job_id": d["jobs"][1]["job_id"],
                    "text": "本科及以上学历", "jd_quote": "本科及以上学历",
                    "status": "met", "rationale": "通读简历后认为已满足"}

        def drop_evidence_ids(d):
            d["jobs"][1]["gates"] = [met_gate(d)]

        def empty_evidence_ids(d):
            g = met_gate(d)
            g["evidence_ids"] = []
            d["jobs"][1]["gates"] = [g]

        for fn in (drop_evidence_ids, empty_evidence_ids):
            with self.subTest(variant=fn.__name__):
                errs = vr.check_report(mutate(fn))
                self.assertTrue(any("met 门槛必须引用证据" in e for e in errs), errs)

    def test_wrong_weight_for_importance(self):
        def m(d):
            d["requirements"][0]["weight"] = 1
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("weight" in e for e in errs), errs)

    def test_score_not_reproducible(self):
        def m(d):
            d["jobs"][0]["score"] = 99
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("分数不可复算" in e for e in errs), errs)

    def test_unknown_count_mismatch(self):
        def m(d):
            d["jobs"][0]["unknown_count"] += 1
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("unknown_count" in e for e in errs), errs)

    def test_suggestion_must_follow_decision_table(self):
        def m(d):
            d["jobs"][0]["suggestion"] = "prioritize"
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("决策表不一致" in e for e in errs), errs)

    def test_hold_without_unmet_gate_rejected(self):
        """hold 只能由已证实的 unmet 门槛触发；凭低分给 hold 一律拒绝。"""
        data = mutate(lambda d: d["jobs"][0].update(suggestion="hold"))
        errs = vr.check_report(data)
        self.assertTrue(any("决策表不一致" in e for e in errs), errs)

    def test_rank_not_permutation(self):
        def m(d):
            d["jobs"][0]["rank"] = 2
            d["jobs"][1]["rank"] = 2
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("1..n" in e for e in errs), errs)

    def test_rewrite_must_belong_to_primary(self):
        def m(d):
            d["rewrites"][0]["job_id"] = d["jobs"][1]["job_id"]
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("只属于主目标" in e for e in errs), errs)

    def test_pending_fill_must_not_produce_copyable_text(self):
        def m(d):
            rw = d["rewrites"][0]
            rw["pending_fill"] = True
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("待补项不得产出" in e for e in errs), errs)

    def test_actions_must_be_three_for_primary(self):
        def m(d):
            d["actions"] = d["actions"][:2]
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("恰好 3 项" in e for e in errs), errs)

    def test_dangling_evidence_reference(self):
        def m(d):
            d["requirements"][0]["evidence_ids"] = ["ev-does-not-exist"]
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("evidence_id 无法解析" in e for e in errs), errs)

    def test_merged_duplicate_stays_out_of_scoring(self):
        """重复/同义要求 merged_into 后不重复计权：分数保持不变。"""
        def m(d):
            base = next(r for r in d["requirements"] if r["job_id"] == "job-a1")
            d["requirements"].append({
                "req_id": "req-a1-dup", "job_id": "job-a1", "text": base["text"] + "（重复条款）",
                "jd_quote": base["jd_quote"], "locator": base["locator"],
                "category": base["category"], "importance": "must", "importance_source": "jd_explicit",
                "status": "supported", "evidence_ids": base["evidence_ids"], "answer_ids": [],
                "rationale": "与原条同义，已合并", "weight": 3, "merged_into": base["req_id"]})
        data = mutate(m)
        self.assertEqual(vr.check_report(data), [], "同义重复条合并后必须仍是合法数据")
        self.assertEqual(data["jobs"][0]["score"], BASE["jobs"][0]["score"],
                         "关键词堆砌/重复条款不得改变分数")

    def test_merged_entry_with_unknown_status_rejected(self):
        def m(d):
            d["requirements"][0]["merged_into"] = d["requirements"][1]["req_id"]
            d["requirements"][0]["status"] = "unknown"
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("被去重条目不应再有 unknown" in e for e in errs), errs)


class TestInsufficientPath(unittest.TestCase):
    def test_fake_zero_score_rejected(self):
        """无可判定要求时给 0 分 = 伪装评分，必须拒绝。"""
        data = mutate(lambda d: d.update(requirements=[]))
        errs = vr.check_report(data)
        self.assertTrue(any("不得出总分" in e for e in errs), errs)

    def test_insufficient_input_requires_null_score(self):
        def m(d):
            d["requirements"] = [r for r in d["requirements"] if r["job_id"] != "job-a2"]
            d["jobs"][1]["scoring_status"] = "insufficient_input"
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("score 必须为 null" in e for e in errs), errs)

    def test_insufficient_with_null_score_is_valid(self):
        def m(d):
            d["requirements"] = [r for r in d["requirements"] if r["job_id"] != "job-a2"]
            d["jobs"][1].update(scoring_status="insufficient_input", score=None, unknown_count=0)
        # 注意：变体/改写仍引用 job-a1；rank 1..n 仍成立
        errs = vr.check_report(mutate(m))
        self.assertEqual(errs, [], errs)


class TestSharePrivacy(unittest.TestCase):
    def test_private_marker_leak_rejected(self):
        def m(d):
            d["share_payload"]["headline_findings"] = ["李晓晓的简历匹配度优秀"]
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("李晓晓" in e for e in errs), errs)

    def test_email_and_phone_leak_rejected(self):
        def m(d):
            d["share_payload"]["gate_notes"] = ["联系 lixiaoxiao@example.com 或 13800001234"]
        errs = vr.check_report(mutate(m))
        joined = "\n".join(errs)
        self.assertIn("邮箱", joined)
        self.assertIn("手机号", joined)

    def test_extra_share_key_rejected(self):
        def m(d):
            d["share_payload"]["resume_text"] = "整份简历"
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("resume_text" in e for e in errs), "share_payload 必须锁死白名单")

    def test_score_label_semantics(self):
        def m(d):
            d["share_payload"]["score_label"] = "ATS 得分"
        errs = vr.check_report(mutate(m))
        self.assertTrue(errs, "score_label 只能是「简历证据匹配度」")


class TestAnswerVariants(unittest.TestCase):
    def test_variant_rescore_mismatch_rejected(self):
        def m(d):
            d["answer_variants"][0]["job_scores"]["job-a1"] = 100
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("变体分数不可复算" in e for e in errs), errs)

    def test_variant_score_change_recorded(self):
        def m(d):
            r = next(r for r in d["requirements"] if r["job_id"] == "job-a2")
            r["status"] = "supported"  # 未登记变体的状态变化 → 分数变化未记录
        errs = vr.check_report(mutate(m))
        self.assertTrue(any("分数变化未记录" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
