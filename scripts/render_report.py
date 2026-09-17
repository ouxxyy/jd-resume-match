#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_report.py — T3 确定性单文件互动 HTML 报告渲染器。

职责与原则：
  * 纯渲染：输入符合 jd-match-report/0.1.0 契约的 JSON 数据，产出自包含单文件 HTML。
  * 渲染器无算分权：绝对不修改、重算或编造任何分数或门槛判定，完全由输入数据驱动。
  * 零外部依赖：纯 Python 标准库 + 纯原生 HTML/CSS/JS/SVG，离线可用（file://）。
  * 脚本与材料安全：对材料中的任何特殊文本做安全嵌入，杜绝 XSS 逃逸。

用法：
  python3 scripts/render_report.py --input examples/case-a-freshgrad-ops/expected.json --output dist/report-a.html
  # 带内容编排 JSON（jd-match-editorial/0.1.0）→ 渲染编辑批注风报告（MYW-69 第 4 步）：
  python3 scripts/render_report.py --input <报告>.json --editorial <编排>.json --output dist/report-a.html
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA_VERSION = "jd-match-report/0.1.0"
RUBRIC_VERSION = "jd-match-rubric/0.1.0"

DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"

REQUIRED_TOP_FIELDS = [
    "schema_version", "rubric_version", "jobs", "requirements",
    "evidence", "answers", "primary_job_id", "rewrites", "actions", "share_payload"
]


def validate_input_data(data: Dict[str, Any]) -> None:
    """做渲染前的快速契约健全性检查，防止渲染残缺空壳。"""
    if not isinstance(data, dict):
        raise ValueError("输入数据必须是 JSON 对象 (dict)")

    missing = [f for f in REQUIRED_TOP_FIELDS if f not in data]
    if missing:
        raise ValueError(f"输入数据缺少必要契约字段: {missing}")

    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version 不匹配: 期望 {SCHEMA_VERSION}，收到 {data.get('schema_version')}")


def safe_json_embed(data: Dict[str, Any]) -> str:
    """将字典序列化为安全的内嵌 JSON 字符串，防止 </script> 截断攻击。"""
    raw_json = json.dumps(data, ensure_ascii=False)
    # 阻止在 script 标签内被提前闭合
    safe_json = raw_json.replace("</", "<\\/")
    return safe_json


def render_report(data: Dict[str, Any], template_path: Optional[Path] = None) -> str:
    """将契约数据渲染进 HTML 模板中，返回完整的单文件 HTML 字符串。"""
    validate_input_data(data)

    tpl_path = template_path or DEFAULT_TEMPLATE_PATH
    if not tpl_path.exists():
        raise FileNotFoundError(f"未找到报告模板文件: {tpl_path}")

    template_content = tpl_path.read_text(encoding="utf-8")

    placeholder = "/* __REPORT_DATA_JSON__ */ null"
    if placeholder not in template_content:
        raise ValueError(f"模板中未找到数据挂载占位符: {placeholder}")

    injected_json = safe_json_embed(data)
    rendered_html = template_content.replace(placeholder, injected_json)

    return rendered_html


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 JD vs 简历匹配度互动 HTML 报告")
    parser.add_argument("--input", "-i", required=True, help="输入的契约 JSON 文件路径")
    parser.add_argument("--output", "-o", required=True, help="输出的 HTML 报告文件路径")
    parser.add_argument("--template", "-t", default=None, help="自定义模板路径（可选）")
    parser.add_argument("--editorial", "-e", default=None,
                        help="内容编排 JSON（jd-match-editorial/0.1.0，可选）；"
                             "提供时渲染编辑批注风报告，不提供时走原有模板，旧输入行为不变")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    tpl_path = Path(args.template) if args.template else None

    if not input_path.exists():
        print(f"[错误] 输入文件不存在: {input_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        if args.editorial:
            # 编辑批注风链路（MYW-69）：表达层内容来自内容编排 JSON，分数/状态仍只读报告数据
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import render_editorial
            ed_path = Path(args.editorial)
            if not ed_path.exists():
                print(f"[错误] 内容编排文件不存在: {ed_path}", file=sys.stderr)
                return 1
            editorial = json.loads(ed_path.read_text(encoding="utf-8"))
            errors = render_editorial.validate_editorial(data, editorial)
            if errors:
                print(f"[错误] 内容编排契约校验失败（{len(errors)} 项）：", file=sys.stderr)
                for e in errors:
                    print(f"  ✗ {e}", file=sys.stderr)
                return 1
            rendered = render_editorial.render_editorial_report(data, editorial)
        else:
            rendered = render_report(data, template_path=tpl_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        mode = "编辑批注风报告" if args.editorial else "报告"
        print(f"[成功] {mode}已渲染生成: {output_path} ({len(rendered)} 字符)")
        return 0
    except Exception as e:
        print(f"[错误] 渲染失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
