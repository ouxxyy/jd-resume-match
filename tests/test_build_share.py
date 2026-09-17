# -*- coding: utf-8 -*-
"""test_build_share.py — T3 独立脱敏分享卡生成器单元测试与独立性验证。"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_share as bs  # noqa: E402

CASE_A_PATH = ROOT / "examples/case-a-freshgrad-ops/expected.json"
CASE_B_PATH = ROOT / "examples/case-b-2yr-data-dev/expected.json"
CASE_A = json.loads(CASE_A_PATH.read_text(encoding="utf-8"))
CASE_B = json.loads(CASE_B_PATH.read_text(encoding="utf-8"))


class TestBuildShare(unittest.TestCase):
    def test_build_share_case_a_success(self):
        share_html = bs.build_share_html(CASE_A)
        self.assertIsInstance(share_html, str)
        self.assertIn("<!DOCTYPE html>", share_html)
        self.assertIn("JOB FIT REPORT", share_html)
        self.assertIn("新媒体运营专员", share_html)
        self.assertIn("75", share_html)

    def test_build_share_case_b_success(self):
        share_html = bs.build_share_html(CASE_B)
        self.assertIsInstance(share_html, str)
        self.assertIn("数据分析师", share_html)
        self.assertIn("83", share_html)

    def test_no_raw_resume_or_private_data_in_share_html(self):
        """核心隐私断言：share.html 绝对不包含原简历来源、证据段落或被标记的私密词。"""
        share_html = bs.build_share_html(CASE_A)

        # 检查 markers
        for marker in CASE_A.get("private_markers", []):
            self.assertNotIn(marker, share_html, f"私密标记 {marker} 绝不能出现在分享 HTML 中")

        # 检查原简历特有内容不出现在分享 HTML 中
        self.assertNotIn("某省大学", share_html)
        self.assertNotIn("lixiaoxiao@example.com", share_html)
        self.assertNotIn("13800001234", share_html)

    def test_privacy_leak_interception(self):
        """当 share_payload 被恶意或意外污染时，build_share 必须拒绝生成。"""
        data = copy.deepcopy(CASE_A)
        data["share_payload"]["headline_findings"].append("李晓晓 同学成果展示")

        with self.assertRaises(ValueError) as ctx:
            bs.build_share_html(data)
        self.assertIn("private_marker", str(ctx.exception))

    def test_extra_key_interception(self):
        """白名单外字段必须被拦截。"""
        data = copy.deepcopy(CASE_B)
        data["share_payload"]["candidate_phone"] = "13900000000"

        with self.assertRaises(ValueError) as ctx:
            bs.build_share_html(data)
        self.assertIn("白名单外字段", str(ctx.exception))

    def test_case_id_js_escape_defense_in_depth(self):
        """纵深防御测试：case_id 内插进 JS 字符串前必须安全转义单引号、反斜杠与闭合标签。"""
        # 1. 单元测试 escape_js_string 辅助函数
        raw = "payload's\\test\nvalue</script>"
        escaped = bs.escape_js_string(raw)
        self.assertIn("\\'", escaped)
        self.assertIn("\\\\", escaped)
        self.assertIn("\\n", escaped)
        self.assertNotIn("</script>", escaped)
        self.assertIn("<\\/script>", escaped)

        # 2. 全流程测试：特殊 case_id 安全内插进 share.html
        data = copy.deepcopy(CASE_A)
        data["case_id"] = "case-a'injection\\break\n</script>"
        share_html = bs.build_share_html(data)
        # 验证不会出现未转义的单引号拼接破坏 JS 语法
        self.assertIn("share-card-case-a\\'injection\\\\break\\n<\\/script>.png", share_html)
        self.assertNotIn("share-card-case-a'injection", share_html)


if __name__ == "__main__":
    unittest.main()
