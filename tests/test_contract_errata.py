# -*- coding: utf-8 -*-
"""MYW-58 报备的两项 T1 契约修订回归测试（2026-09-11，T1 落地）。

修订 1：private_markers.items.minLength 4 → 2（中文两字/三字姓名标记合法；单字符拒绝）。
修订 2：synthetic const:true → boolean（真实材料报告 synthetic=false 必须可通过校验）。
红线：本仓库 examples/ 黄金案例仍必须 synthetic=true，禁止真实材料入库。

MYW-64 增补（2026-09-12）：门槛证据规则同判收口——met 门槛必须引用证据，
文案与 T2 MYW-62 落地的规则逐字一致（unmet 规则两套实现此前均已强制）。

两套实现（T1 reference_score.py 与 T2 validate_report.py）必须对同一 schema 文件同判。
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reference_score as rs  # noqa: E402
import validate_report as vr  # noqa: E402  T2 校验器，交叉验证

GOLDEN_PATHS = [
    ROOT / "examples/case-a-freshgrad-ops/expected.json",
    ROOT / "examples/case-b-2yr-data-dev/expected.json",
    ROOT / "examples/supplements/sup-market.expected.json",
    ROOT / "examples/supplements/sup-design.expected.json",
]
CASE_A = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))


def real_material_copy():
    """把 Case A 改造成「真实材料」报告：synthetic=false，其余结构不变。"""
    d = copy.deepcopy(CASE_A)
    d["synthetic"] = False
    d["case_id"] = "real-material-e2e"
    return d


class TestSchemaErratumPinned(unittest.TestCase):
    """schema 文件必须钉住修订后的值，防止回退。"""

    def test_schema_file_pins_revised_values(self):
        raw = json.loads(vr.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["properties"]["private_markers"]["items"]["minLength"], 2)
        self.assertEqual(raw["properties"]["synthetic"].get("type"), "boolean")
        self.assertNotIn("const", raw["properties"]["synthetic"])

    def test_t2_minlength_override_is_inert_after_revision(self):
        """T2 的 MYW-58 临时覆盖声明过「schema 修订后自动失效」，必须验证失效。"""
        schema = vr.load_schema()
        self.assertEqual(schema["properties"]["private_markers"]["items"]["minLength"], 2)
        self.assertNotIn("deviation_note", schema["properties"]["private_markers"])


class TestRealMaterialAccepted(unittest.TestCase):
    """修订 2 的目的：真实材料报告不再被契约阻断。"""

    def test_synthetic_false_passes_t1_checker(self):
        self.assertEqual(rs.check_contract(real_material_copy()), [])

    def test_synthetic_false_passes_t2_validator(self):
        self.assertEqual(vr.check_report(real_material_copy()), [])

    def test_real_material_score_recomputes_unchanged(self):
        data = real_material_copy()
        self.assertEqual(rs.score_of("job-a1", data["requirements"]), 75)
        self.assertEqual(rs.score_of("job-a2", data["requirements"]), 29)

    def test_non_boolean_synthetic_rejected_by_both(self):
        for bad in ("true", 1, None):
            with self.subTest(bad=bad):
                data = real_material_copy()
                data["synthetic"] = bad
                self.assertTrue(any("布尔" in e for e in rs.check_contract(data)))
                self.assertTrue(vr.check_report(data))


class TestMarkerMinLengthTwo(unittest.TestCase):
    """修订 1 的目的：两字/三字中文姓名标记合法，单字符拒绝。"""

    def test_two_char_name_marker_accepted_by_both(self):
        data = copy.deepcopy(CASE_A)
        data["private_markers"] = ["王成", "13900005678"]
        self.assertEqual(rs.check_contract(data), [])
        self.assertEqual(vr.check_report(data), [])

    def test_three_char_name_marker_accepted_by_both(self):
        data = copy.deepcopy(CASE_A)
        data["private_markers"] = ["李晓晓"]
        self.assertEqual(rs.check_contract(data), [])
        self.assertEqual(vr.check_report(data), [])

    def test_single_char_marker_rejected_by_both(self):
        data = copy.deepcopy(CASE_A)
        data["private_markers"] = ["王"]
        t1_errors = rs.check_contract(data)
        self.assertTrue(any("2 个字符" in e for e in t1_errors), t1_errors)
        t2_errors = vr.check_report(data)
        self.assertTrue(any("minLength=2" in e for e in t2_errors), t2_errors)

    def test_markers_still_required(self):
        data = copy.deepcopy(CASE_A)
        data["private_markers"] = []
        self.assertTrue(any("不能为空" in e for e in rs.check_contract(data)))
        self.assertTrue(vr.check_report(data))


class TestMetGateEvidenceRule(unittest.TestCase):
    """MYW-64 同判收口：met 门槛必须引用证据，两套实现同判且文案逐字一致。

    schema 层不要求 gates 携带 evidence_ids（required 之外），因此两种变体
    都必须由语义规则拒绝，而不是被结构校验提前拦截。
    """

    MET_TEXT = "met 门槛必须引用证据，禁止无引用的满足判断"

    def met_gate_without_evidence(self, variant):
        """把 Case A 真实的 met 门槛 gate-a1-g1（原引 ev-a7）改成无证据形态。"""
        d = copy.deepcopy(CASE_A)
        gate = d["jobs"][0]["gates"][0]
        self.assertEqual(gate["gate_id"], "gate-a1-g1")
        self.assertEqual(gate["status"], "met")
        if variant == "missing_key":
            del gate["evidence_ids"]
        else:
            gate["evidence_ids"] = []
        return d

    def test_met_gate_without_evidence_rejected_by_both(self):
        for variant in ("missing_key", "empty_list"):
            with self.subTest(variant=variant):
                data = self.met_gate_without_evidence(variant)
                t1_errors = rs.check_contract(data)
                self.assertTrue(any(self.MET_TEXT in e for e in t1_errors), t1_errors)
                t2_errors = vr.check_report(data)
                self.assertTrue(any(self.MET_TEXT in e for e in t2_errors), t2_errors)


class TestRepoRedLine(unittest.TestCase):
    """契约放宽不等于仓库红线放宽：入库的黄金案例必须始终是合成材料。"""

    def test_committed_golden_cases_stay_synthetic(self):
        for p in GOLDEN_PATHS:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIs(data["synthetic"], True, f"{p.name} 禁止携带真实材料入库")


if __name__ == "__main__":
    unittest.main()
