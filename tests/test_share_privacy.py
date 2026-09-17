# -*- coding: utf-8 -*-
"""分享隐私红蓝队测试：对 share_payload 白名单与标记扫描做定向攻击。"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reference_score as rs  # noqa: E402

CASE_A = json.loads((ROOT / "examples/case-a-freshgrad-ops/expected.json").read_text(encoding="utf-8"))
CASE_B = json.loads((ROOT / "examples/case-b-2yr-data-dev/expected.json").read_text(encoding="utf-8"))


class TestSharePrivacy(unittest.TestCase):
    def test_golden_cases_pass_privacy_scan(self):
        for data in (CASE_A, CASE_B):
            self.assertEqual(rs.check_share_privacy(data), [],
                             "黄金案例的分享载荷必须通过隐私扫描")

    def test_attack_name_leak_detected(self):
        data = copy.deepcopy(CASE_A)
        data["share_payload"]["headline_findings"].append("李晓晓同学匹配度很高")
        errors = rs.check_share_privacy(data)
        self.assertTrue(any("private_marker" in e for e in errors), "姓名泄漏必须被拦截")

    def test_attack_phone_leak_detected(self):
        data = copy.deepcopy(CASE_A)
        data["share_payload"]["headline_findings"].append("联系电话 13800001234 欢迎骚扰")
        errors = rs.check_share_privacy(data)
        self.assertTrue(any("手机号" in e for e in errors), "手机号泄漏必须被拦截")

    def test_attack_email_leak_detected(self):
        data = copy.deepcopy(CASE_A)
        data["share_payload"]["headline_findings"].append("邮箱 lixiaoxiao@example.com")
        errors = rs.check_share_privacy(data)
        self.assertTrue(any("邮箱" in e for e in errors), "邮箱泄漏必须被拦截")

    def test_attack_extra_key_detected(self):
        data = copy.deepcopy(CASE_B)
        data["share_payload"]["candidate_name"] = "王成"
        data["share_payload"]["resume_raw_text"] = "……原简历全文……"
        errors = rs.check_share_privacy(data)
        self.assertTrue(any("白名单外字段" in e for e in errors), "白名单外字段必须被拦截")

    def test_attack_school_marker_detected(self):
        data = copy.deepcopy(CASE_B)
        data["share_payload"]["gate_notes"].append("毕业于某理工大学")
        errors = rs.check_share_privacy(data)
        self.assertTrue(any("private_marker" in e for e in errors), "学校信息泄漏必须被拦截")

    def test_disclaimer_must_keep_score_semantics(self):
        for data in (CASE_A, CASE_B):
            self.assertIn("面试概率", data["share_payload"]["disclaimer"],
                          "分享卡必须声明分数不是面试概率")


if __name__ == "__main__":
    unittest.main()
