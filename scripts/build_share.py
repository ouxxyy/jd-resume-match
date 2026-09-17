#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_share.py — T3 独立脱敏分享资产生成器。

原则与红线：
  * 白名单机制：仅消费 share_payload，严禁将原简历或任何私密字段（姓名/电话/邮箱/公司/学校等）埋入 DOM 或数据属性。
  * 隐私扫描：必须通过 private_markers 扫描与电话/邮箱正则检查；拦截任何潜在泄漏。
  * 独立自包含：产出的 share.html 必须可完全脱离完整报告独立渲染并直接在浏览器中打开。
  * 真实导出能力：内置高质量内联 Canvas 图片导出（PNG）与无损打印样式。

用法：
  python3 scripts/build_share.py --input examples/case-a-freshgrad-ops/expected.json --output examples/case-a-freshgrad-ops/share.html
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SHARE_ALLOWED_KEYS = {
    "standalone", "anonymized", "score", "score_label", "job_title", "job_category",
    "headline_findings", "gate_notes", "disclaimer",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def check_share_privacy(data: Dict[str, Any]) -> List[str]:
    """严格隐私扫描：白名单键扫描、私密标记扫描、手机/邮箱正则扫描。"""
    errors: List[str] = []
    sp = data.get("share_payload")
    if not isinstance(sp, dict):
        return ["缺少或非法的 share_payload"]

    # 1. 检查白名单外字段
    extra = set(sp.keys()) - SHARE_ALLOWED_KEYS
    if extra:
        errors.append(f"share_payload 包含白名单外字段: {sorted(extra)}")

    # 2. 必须声明 standalone 与 anonymized 为 true
    if sp.get("standalone") is not True:
        errors.append("share_payload 必须声明 standalone: true")
    if sp.get("anonymized") is not True:
        errors.append("share_payload 必须声明 anonymized: true")

    # 3. 收集 share_payload 中出现的所有字符串进行敏感词排查
    def collect_strings(obj: Any) -> List[str]:
        strs = []
        if isinstance(obj, str):
            strs.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                strs.extend(collect_strings(item))
        elif isinstance(obj, dict):
            for v in obj.values():
                strs.extend(collect_strings(v))
        return strs

    all_texts = collect_strings(sp)
    full_corpus = " \n ".join(all_texts)

    # 4. 扫描 private_markers
    markers = data.get("private_markers", [])
    for m in markers:
        if isinstance(m, str) and len(m) >= 2 and m in full_corpus:
            errors.append(f"share_payload 命中 private_marker: '{m}'")

    # 5. 正则扫描电话与邮箱
    if EMAIL_RE.search(full_corpus):
        errors.append("share_payload 疑似包含邮箱地址")
    if PHONE_RE.search(full_corpus):
        errors.append("share_payload 疑似包含手机号")

    # 6. 免责声明语义核查
    disclaimer = sp.get("disclaimer", "")
    if "面试概率" not in disclaimer:
        errors.append("disclaimer 必须声明分数不代表面试概率")

    return errors


def escape_js_string(val: Any) -> str:
    """对内插进 JS 单引号字符串字面量的变量做安全转义（纵深防御）。

    转义反斜杠、单引号、换行符等特殊字符，并阻断 </script> 闭合标签逃逸。
    """
    s = str(val)
    s = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    s = s.replace("</", "<\\/")
    return s


def build_share_html(data: Dict[str, Any]) -> str:
    """生成纯净脱敏的单文件 HTML 分享卡资产。"""
    privacy_errors = check_share_privacy(data)
    if privacy_errors:
        raise ValueError(f"脱敏分享卡生成被隐私策略拦截:\n" + "\n".join(privacy_errors))

    sp = data["share_payload"]
    case_id = data.get("case_id", "report")
    safe_case_id = escape_js_string(case_id)

    score_val_str = str(sp.get("score")) if sp.get("score") is not None else "--"
    score_label = html.escape(sp.get("score_label", "简历证据匹配度"))
    job_title = html.escape(sp.get("job_title", "目标岗位"))
    job_category = html.escape(sp.get("job_category", ""))
    disclaimer = html.escape(sp.get("disclaimer", ""))

    findings_items = "".join(
        f'<li class="finding-item"><span class="bullet">✓</span><span>{html.escape(f)}</span></li>'
        for f in sp.get("headline_findings", [])
    )

    gate_items = "".join(
        f'<li class="gate-item"><span class="bullet-gate">!</span><span>{html.escape(g)}</span></li>'
        for g in sp.get("gate_notes", [])
    )

    # 序列化白名单 JSON（且仅包含白名单字段）供页面内 Canvas 绘图使用
    clean_sp_json = json.dumps(sp, ensure_ascii=False).replace("</", "<\\/")

    share_html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>求职体检卡 · 脱敏分享资产</title>
  <style>
    :root {{
      --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --primary: #2563eb;
      --border: #e2e8f0;
      --shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
    }}
    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: var(--font-sans);
      background-color: var(--bg);
      color: var(--text-main);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
      -webkit-font-smoothing: antialiased;
    }}
    .share-container {{
      width: 100%;
      max-width: 480px;
    }}
    .action-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      font-weight: 600;
      padding: 8px 16px;
      border-radius: 9999px;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text-main);
      cursor: pointer;
      transition: all 0.2s ease;
      text-decoration: none;
    }}
    .btn-primary {{
      background: #0f172a;
      color: #fff;
      border-color: #0f172a;
    }}
    .btn:hover {{
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }}
    .share-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 32px 28px;
      box-shadow: var(--shadow);
      position: relative;
    }}
    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
    }}
    .card-brand {{
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      color: var(--primary);
      text-transform: uppercase;
    }}
    .badge-privacy {{
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 9999px;
      background: #f1f5f9;
      color: var(--text-muted);
    }}
    .score-section {{
      text-align: center;
      padding: 20px 0 24px;
      border-top: 1px solid #f1f5f9;
      border-bottom: 1px solid #f1f5f9;
      margin-bottom: 24px;
    }}
    .score-label {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 6px;
    }}
    .score-num {{
      font-size: 72px;
      font-weight: 900;
      color: var(--text-main);
      line-height: 1;
      letter-spacing: -0.03em;
    }}
    .job-title-row {{
      font-size: 18px;
      font-weight: 700;
      color: var(--text-main);
      margin-top: 10px;
    }}
    .findings-section {{
      margin-bottom: 24px;
    }}
    .findings-title {{
      font-size: 12px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 12px;
    }}
    .findings-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .finding-item {{
      font-size: 13px;
      color: #334155;
      display: flex;
      align-items: flex-start;
      gap: 8px;
      line-height: 1.5;
    }}
    .bullet {{
      color: var(--primary);
      font-weight: 700;
    }}
    .gate-item {{
      font-size: 13px;
      color: #b45309;
      display: flex;
      align-items: flex-start;
      gap: 8px;
      line-height: 1.5;
    }}
    .bullet-gate {{
      color: #f59e0b;
      font-weight: 700;
    }}
    .card-footer {{
      font-size: 11px;
      color: var(--text-muted);
      line-height: 1.5;
      text-align: center;
      border-top: 1px dashed var(--border);
      padding-top: 16px;
    }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .action-bar {{ display: none; }}
      .share-card {{ box-shadow: none; border: 1px solid #ccc; }}
    }}
  </style>
</head>
<body>

<div class="share-container">
  <div class="action-bar">
    <span style="font-size: 12px; color: var(--text-muted);">仅含脱敏数据 · 安全分享</span>
    <div style="display: flex; gap: 8px;">
      <button class="btn btn-primary" id="btnExportSharePng">导出 PNG 图片</button>
      <button class="btn" onclick="window.print()">打印卡片</button>
    </div>
  </div>

  <div class="share-card" id="shareCardDOM">
    <div class="card-top">
      <span class="card-brand">JOB FIT REPORT</span>
      <span class="badge-privacy">已脱敏 · 无身份信息</span>
    </div>

    <div class="score-section">
      <div class="score-label">{score_label}</div>
      <div class="score-num">{score_val_str}</div>
      <div class="job-title-row">{job_title} {f'· {job_category}' if job_category else ''}</div>
    </div>

    <div class="findings-section">
      <div class="findings-title">核心诊断发现与依据</div>
      <ul class="findings-list">
        {findings_items}
        {gate_items}
      </ul>
    </div>

    <div class="card-footer">
      {disclaimer}
    </div>
  </div>
</div>

<script>
(function() {{
  const shareData = {clean_sp_json};

  document.getElementById('btnExportSharePng').addEventListener('click', function() {{
    const width = 800;
    const height = 1000;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');

    // 背景
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, width, height);

    // 卡片外框
    ctx.fillStyle = '#ffffff';
    roundRect(ctx, 40, 40, 720, 920, 24);
    ctx.fill();
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 2;
    ctx.stroke();

    // 头部文字
    ctx.fillStyle = '#2563eb';
    ctx.font = 'bold 20px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText('JOB FIT REPORT', 80, 100);

    ctx.fillStyle = '#64748b';
    ctx.font = '16px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText('已脱敏求职体检卡 · 纯净数据', 480, 100);

    // 分界线
    ctx.strokeStyle = '#f1f5f9';
    ctx.beginPath();
    ctx.moveTo(80, 130);
    ctx.lineTo(720, 130);
    ctx.stroke();

    // 分数区
    ctx.fillStyle = '#64748b';
    ctx.font = '18px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(shareData.score_label || '简历证据匹配度', 80, 180);

    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 88px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const scoreVal = shareData.score !== null ? String(shareData.score) : '--';
    ctx.fillText(scoreVal, 80, 270);

    ctx.fillStyle = '#334155';
    ctx.font = 'bold 28px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(shareData.job_title || '目标岗位', 80, 325);

    // 核心发现
    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 20px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText('核心诊断发现：', 80, 400);

    let y = 450;
    ctx.font = '18px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillStyle = '#334155';

    if (Array.isArray(shareData.headline_findings)) {{
      shareData.headline_findings.forEach(hf => {{
        ctx.fillStyle = '#2563eb';
        ctx.fillText('•', 80, y);
        ctx.fillStyle = '#334155';
        wrapText(ctx, hf, 110, y, 590, 28);
        y += 65;
      }});
    }}

    if (Array.isArray(shareData.gate_notes)) {{
      shareData.gate_notes.forEach(gn => {{
        ctx.fillStyle = '#f59e0b';
        ctx.fillText('!', 80, y);
        ctx.fillStyle = '#b45309';
        wrapText(ctx, gn, 110, y, 590, 28);
        y += 65;
      }});
    }}

    // 声明
    ctx.fillStyle = '#94a3b8';
    ctx.font = '14px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    wrapText(ctx, shareData.disclaimer || '', 80, 880, 640, 22);

    const link = document.createElement('a');
    link.download = 'share-card-{safe_case_id}.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
  }});

  function roundRect(ctx, x, y, w, h, r) {{
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }}

  function wrapText(ctx, text, x, y, maxWidth, lineHeight) {{
    let words = String(text);
    let line = '';
    for (let n = 0; n < words.length; n++) {{
      let testLine = line + words[n];
      let metrics = ctx.measureText(testLine);
      if (metrics.width > maxWidth && n > 0) {{
        ctx.fillText(line, x, y);
        line = words[n];
        y += lineHeight;
      }} else {{
        line = testLine;
      }}
    }}
    ctx.fillText(line, x, y);
  }}
}})();
</script>

</body>
</html>"""

    return share_html_template


def main() -> int:
    parser = argparse.ArgumentParser(description="生成脱敏的独立分享卡 HTML 资产")
    parser.add_argument("--input", "-i", required=True, help="输入的契约 JSON 文件路径")
    parser.add_argument("--output", "-o", required=True, help="输出的分享卡 HTML 文件路径")

    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[错误] 输入文件不存在: {input_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        share_html = build_share_html(data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(share_html, encoding="utf-8")
        print(f"[成功] 脱敏分享卡已生成: {output_path} ({len(share_html)} 字符)")
        return 0
    except Exception as e:
        print(f"[错误] 生成分享资产失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
