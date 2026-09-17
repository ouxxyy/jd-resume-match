# -*- coding: utf-8 -*-
"""test_render_report.py — T3 互动 HTML 报告渲染器的单元测试与契约防护测试。"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_report as rr  # noqa: E402

CASE_A_PATH = ROOT / "examples/case-a-freshgrad-ops/expected.json"
CASE_B_PATH = ROOT / "examples/case-b-2yr-data-dev/expected.json"
CASE_A = json.loads(CASE_A_PATH.read_text(encoding="utf-8"))
CASE_B = json.loads(CASE_B_PATH.read_text(encoding="utf-8"))


class TestRenderReport(unittest.TestCase):
    def test_render_case_a_success(self):
        html_content = rr.render_report(CASE_A)
        self.assertIsInstance(html_content, str)
        self.assertGreater(len(html_content), 10000)
        self.assertIn("<!DOCTYPE html>", html_content)
        self.assertIn("求职体检单", html_content)
        self.assertIn("新媒体运营专员", html_content)

    def test_render_case_b_success(self):
        html_content = rr.render_report(CASE_B)
        self.assertIsInstance(html_content, str)
        self.assertIn("数据分析师", html_content)
        self.assertIn("建议暂缓投递", html_content)

    def test_zero_external_network_dependencies(self):
        """严禁引用外部 CDN、在线脚本或在线样式。"""
        html_content = rr.render_report(CASE_A)
        # 不得有外部 script src
        self.assertNotIn('<script src="http', html_content)
        # 不得有外部 link href (如 Google Fonts, Tailwind CDN)
        self.assertNotIn('<link rel="stylesheet" href="http', html_content)
        self.assertNotIn('<link href="http', html_content)
        # 不得有外部 img src
        self.assertNotIn('<img src="http', html_content)

    def test_essential_components_present(self):
        """核心交互组件与模块挂载点必须存在。"""
        html_content = rr.render_report(CASE_A)
        expected_ids = [
            'id="heroScoreNum"',
            'id="heroJobTitle"',
            'id="heroSuggestionBanner"',
            'id="jobsListGrid"',
            'id="requirementsList"',
            'id="rewritesList"',
            'id="actionsList"',
            'id="shareModal"',
            'id="btnExportCardPng"',
        ]
        for comp_id in expected_ids:
            self.assertIn(comp_id, html_content, f"HTML 必须包含核心组件挂载点 {comp_id}")

    def test_xss_and_script_tag_escape(self):
        """即使材料中含有恶意 </script><script> 也能安全嵌套。"""
        data = copy.deepcopy(CASE_A)
        malicious_str = '</script><script>alert("pwned")</script>'
        data["requirements"][0]["text"] = malicious_str

        rendered = rr.render_report(data)
        # 确保安全内联转换
        self.assertNotIn("</script><script>alert", rendered)
        self.assertIn("<\\/script><script>alert", rendered)

    def test_missing_required_fields_raises(self):
        bad_data = {"schema_version": "jd-match-report/0.1.0"}
        with self.assertRaises(ValueError):
            rr.render_report(bad_data)

    def test_wrong_schema_version_raises(self):
        bad_data = copy.deepcopy(CASE_A)
        bad_data["schema_version"] = "wrong-version/9.9.9"
        with self.assertRaises(ValueError):
            rr.render_report(bad_data)


if __name__ == "__main__":
    unittest.main()
