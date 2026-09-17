#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_editorial.py — 默认交付链路：编辑批注风通用生成（报告 + 成员卡 + 案例卡 + 发布素材）。

定位与原则（MYW-72/MYW-73 起为唯一默认交付流程）：
  * 表达层渲染器：输入「评分报告 JSON（jd-match-report/0.1.0）+ 内容编排 JSON
    （jd-match-editorial/0.2.0）」，产出成品：报告 HTML、成员版分享卡（默认 1 张）、
    案例版卡片（按编排启用）、卡片预览 HTML（1080×1440）、小红书发布 Markdown。
  * 渲染器无算分权：一切分数、状态、建议只从报告 JSON 读取；内容编排 JSON 只管「怎么说」。
    成员版与案例版共用同一份评分结果与证据，不另算分。
  * 失败即报错：内容编排缺失/校验失败、成员版内容组缺失、PNG 导出失败都明确报错退出，
    不把旧模板报告或仅 HTML 卡片当成完成交付；旧链路（render_report.py 不带 --editorial、
    build_share.py）仅为兼容既有调用保留。
  * 事实纪律进代码：改写后文本的每个数字、每个职责范围词都必须能在改写前文本
    或其引用证据里找到原样出处；JD 引号必须是原文连续子串；发现/标题里的数字
    必须落在证据池内。违反即拒绝渲染。
  * 脱敏隔离：卡片与发布正文只消费内容编排 JSON 的白名单内容，生成前对全部
    分享面字符串做 private_markers / 邮箱 / 手机号扫描；编排声明 redactions 后，
    报告可见原文按白名单泛化，仍有漏网标记即拒绝渲染。
  * 品牌独立：入口/尾注等品牌文案一律来自 references/brand.json（--brand 可换），
    与候选人材料零耦合。
  * 零依赖：Python 3.9+ 标准库 + 原生 HTML/CSS/JS，离线可用（file://）。

用法：
  python3 scripts/render_editorial.py \
    --input examples/case-a-freshgrad-ops/expected.json \
    --editorial examples/case-a-freshgrad-ops/editorial.json \
    --outdir dist/publish/case-a-freshgrad-ops
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EDITORIAL_VERSION = "jd-match-editorial/0.2.0"
LEGACY_EDITORIAL_VERSION = "jd-match-editorial/0.1.0"  # 旧编排仍可读取渲染（案例卡照旧），但缺成员版，不是默认交付口径
VOICE_VERSION = "jd-match-voice/0.2.0"
CARD_W, CARD_H = 1080, 1440
DEFAULT_BRAND_PATH = Path(__file__).resolve().parents[1] / "references" / "brand.json"

# 岗位类别 → 成员卡人话标签（数据里是英文枚举，展示面必须中文）
JOB_CATEGORY_HUMAN = {
    "product": "产品方向", "operations": "运营方向", "marketing": "市场方向",
    "data": "数据方向", "engineering": "工程方向", "design": "设计方向",
    "category_unverified": "岗位方向未核实",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 内部话不出机房（content-standards §2）：机器标识、状态机词、规则引用
INTERNAL_ID_RE = re.compile(r"\b(?:gate|req|ev|ans|rw|act|job)-[a-z0-9]+(?:-[a-z0-9]+)*\b", re.IGNORECASE)
STATUS_WORD_RE = re.compile(r"\b(?:met|unmet|partial|supported|unknown|pending|unclear)\b")
RULE_REF_RE = re.compile(r"§|决策表第|rubric|schema|R1[0-9]\b|docs/")
EMPTY_TALK = ("提升竞争力", "突出优势", "强化亮点", "展现自我", "增加砝码", "进一步优化表述")
SCOPE_WORDS = ("独立", "主导", "负责", "带领", "统筹")

# 判定状态 → 人话（渲染层固定映射，无自由裁量）
REQ_STATUS_HUMAN = {
    "supported": ("有实据", "green"),
    "partial": ("部分满足", "amber"),
    "unclear": ("没写清", "gray"),
    "unknown": ("看不出来", "gray"),
    "unmet": ("明确不满足", "red"),
}
GATE_STATUS_HUMAN = {
    "met": ("核实通过", "green"),
    "pending_confirmation": ("待确认", "amber"),
    "unmet": ("明确不满足", "red"),
}
SUGGESTION_HUMAN = {
    "prioritize": "优先投",
    "revise_then_apply": "改好再投",
    "hold": "先暂缓",
}
IMPORTANCE_HUMAN = {"must": "必须", "normal": "一般", "bonus": "优先项"}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def esc(val: Any) -> str:
    return html.escape(str(val), quote=True)


def md_bold(text: str) -> str:
    """转义后把 **…** 转成 <strong>（内容编排里唯一允许的内联标记）。"""
    out, bold = [], False
    for part in re.split(r"\*\*", text):
        out.append(f"<strong>{esc(part)}</strong>" if bold else esc(part))
        bold = not bold
    return "".join(out)


def seg_html(segments: List[Dict[str, Any]]) -> str:
    """标题段渲染：[{t, style}] + {br: true}；style ∈ red | marker。"""
    parts = []
    for seg in segments:
        if seg.get("br"):
            parts.append("<br>")
            continue
        t = esc(seg.get("t", ""))
        style = seg.get("style")
        if style == "red":
            parts.append(f'<span class="highlight-red">{t}</span>')
        elif style == "marker":
            parts.append(f'<span class="underline-marker">{t}</span>')
        else:
            parts.append(t)
    return "".join(parts)


def human_locator(locator: str, kind: str) -> str:
    """把数据定位符转成人话出处：「src-jd-a1 职责第 1 条」→「JD · 职责第 1 条」。"""
    prefix = "简历" if kind == "resume" else "JD"
    for src_tok in re.findall(r"src-[a-z0-9-]+", locator):
        locator = locator.replace(src_tok + " ", "").replace(src_tok, "")
    return f"{prefix} · {locator.strip()}" if locator.strip() else prefix


def collect_strings(obj: Any) -> List[str]:
    strs: List[str] = []
    if isinstance(obj, str):
        strs.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            strs.extend(collect_strings(item))
    elif isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                strs.append(val)
            else:
                strs.extend(collect_strings(val))
    return strs


# ---------------------------------------------------------------------------
# 品牌配置与渲染级脱敏白名单
# ---------------------------------------------------------------------------

_BRAND: Dict[str, Any] = {}  # generate_bundle/main 装载；测试可直接注入


def load_brand(path: Optional[Path] = None) -> Dict[str, Any]:
    """品牌配置独立于候选人材料：入口、尾注、徽章全部来自 references/brand.json。"""
    p = Path(path) if path else DEFAULT_BRAND_PATH
    if not p.exists():
        raise ValueError(f"品牌配置文件不存在: {p}（品牌文案必须独立配置，渲染器不内置任何品牌）")
    data = json.loads(p.read_text(encoding="utf-8"))
    for key in ("search_entry", "cta"):
        if not data.get(key):
            raise ValueError(f"品牌配置缺少必填字段 {key}: {p}")
    return data


def _brand() -> Dict[str, Any]:
    global _BRAND
    if not _BRAND:
        _BRAND = load_brand()
    return _BRAND


def _build_redactions(ed: Dict[str, Any]) -> List[Tuple[str, str]]:
    """编排声明的渲染级脱敏白名单：[(原文片段, 泛化词)]，按声明顺序应用于报告可见原文。"""
    return [(r["from"], r["to"]) for r in ed.get("redactions", []) if r.get("from")]


def _redact(text: str, reds: List[Tuple[str, str]]) -> str:
    for src, dst in reds:
        text = text.replace(src, dst)
    return text


def _assert_redacted(html_text: str, markers: List[str], reds: List[Tuple[str, str]]) -> None:
    """声明了 redactions 却仍有私密标记出现在可见文本 = 泛化不全，拒绝渲染（视觉隐藏不算脱敏）。"""
    if not reds:
        return  # 未声明脱敏白名单 → 报告按成员私有件处理（完整报告含材料细节，不替用户外发）
    visible = re.sub(r"<[^>]+>", "", html_text)
    visible = html.unescape(visible)
    leaks = [m for m in markers if isinstance(m, str) and len(m) >= 2 and m in visible]
    if leaks:
        raise ValueError(
            "渲染级脱敏不彻底：声明了 redactions 但以下私密标记仍出现在报告可见文本："
            + "、".join(leaks)
            + "。请在编排 redactions 中补齐泛化规则后重试。")


# ---------------------------------------------------------------------------
# 契约校验（结构 + 语义 + 事实纪律 + 表达纪律 + 脱敏）
# ---------------------------------------------------------------------------

def _voice_lint(errors: List[str], where: str, text: str, exempt_jd: bool = False) -> None:
    if not text:
        return
    if INTERNAL_ID_RE.search(text):
        errors.append(f"{where}: 出现内部机器标识（{INTERNAL_ID_RE.search(text).group(0)}），内部话不出机房")
    if STATUS_WORD_RE.search(text):
        errors.append(f"{where}: 出现状态机英文词（{STATUS_WORD_RE.search(text).group(0)}），用人话表述状态")
    if RULE_REF_RE.search(text):
        errors.append(f"{where}: 出现规则引用（§/决策表/rubric/schema 等），规则依据不进用户可见文字")
    for phrase in EMPTY_TALK:
        if phrase in text:
            errors.append(f"{where}: 空话黑名单「{phrase}」，点评必须落到具体锚点")


def _privacy_lint(errors: List[str], where: str, text: str, markers: List[str]) -> None:
    if EMAIL_RE.search(text):
        errors.append(f"{where}: 疑似包含邮箱地址（分享面禁止）")
    if PHONE_RE.search(text):
        errors.append(f"{where}: 疑似包含手机号（分享面禁止）")
    for marker in markers:
        if isinstance(marker, str) and len(marker) >= 2 and marker in text:
            errors.append(f"{where}: 命中私密标记「{marker}」")


def _digits_of(text: str) -> List[str]:
    """提取数字串（事实溯源用）。有序列表编号（行首「1. 」后接空白）是排版不是断言，先剥离。"""
    stripped = re.sub(r"(?m)^\s*\d+[.、)](?=\s|$)", "", text or "")
    return NUM_RE.findall(stripped)


def validate_editorial(report: Dict[str, Any], ed: Dict[str, Any]) -> List[str]:
    """内容编排契约校验：引用可解析、引号逐字、数字有出处、职责词零新增、
    表达纪律与脱敏纪律全过。返回错误列表（空 = 通过）。"""
    errors: List[str] = []

    def err(msg: str) -> None:
        errors.append(msg)

    # 1. 版本与案例对齐（0.1.0 旧编排仅保留读取兼容；默认交付口径是 0.2.0）
    ed_version = ed.get("editorial_version")
    if ed_version not in (EDITORIAL_VERSION, LEGACY_EDITORIAL_VERSION):
        err(f"editorial_version 应为 {EDITORIAL_VERSION}（或兼容读取 {LEGACY_EDITORIAL_VERSION}），实际 {ed_version!r}")
    if ed.get("voice_version") != VOICE_VERSION:
        err(f"voice_version 应为 {VOICE_VERSION}，实际 {ed.get('voice_version')!r}")
    is_v2 = ed_version == EDITORIAL_VERSION
    if is_v2 and not ed.get("member_card"):
        err("0.2.0 编排必须包含 member_card（成员版分享卡内容组，默认交付 1 张；缺失即拒绝渲染，不回退旧模板）")
    if not is_v2 and ed.get("member_card"):
        err(f"{LEGACY_EDITORIAL_VERSION} 编排不含成员版；请升到 {EDITORIAL_VERSION} 或删除 member_card")
    for i, r in enumerate(ed.get("redactions", [])):
        if not isinstance(r, dict) or not r.get("from") or not r.get("to"):
            err(f"redactions[{i}]: 必须是 {{from, to}}，from 为报告中需泛化的原文片段，to 为泛化词")
        elif r.get("from") == r.get("to"):
            err(f"redactions[{i}]: from 与 to 相同，泛化无意义")
    if ed.get("case_id") != report.get("case_id"):
        err(f"case_id 与报告不一致：编排 {ed.get('case_id')!r} vs 报告 {report.get('case_id')!r}")
    if ed.get("job_id") != report.get("primary_job_id"):
        err(f"job_id 必须是主目标岗位（{report.get('primary_job_id')}），实际 {ed.get('job_id')!r}")

    # 编排层永不携带分数（分数只能来自报告 JSON）
    def _walk_no_score(obj: Any, path: str = "$") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key == "score":
                    err(f"{path}.{key}: 内容编排禁止携带 score（分数只能来自评分报告 JSON）")
                _walk_no_score(val, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                _walk_no_score(val, f"{path}[{i}]")
    _walk_no_score(ed)

    jobs = {j["job_id"]: j for j in report["jobs"]}
    reqs = {r["req_id"]: r for r in report["requirements"] if not r.get("merged_into")}
    evs = {e["evidence_id"]: e for e in report["evidence"]}
    answers = {a["answer_id"]: a for a in report.get("answers", [])}
    rws = {r["rewrite_id"]: r for r in report["rewrites"]}
    acts = {a["action_id"]: a for a in report["actions"]}
    gates: Dict[str, dict] = {}
    for job in report["jobs"]:
        for gate in job.get("gates", []):
            gates[gate["gate_id"]] = gate

    primary_id = report["primary_job_id"]
    primary_req_ids = [rid for rid, r in reqs.items() if r["job_id"] == primary_id]
    primary_gate_ids = [gid for gid, g in gates.items() if g["job_id"] == primary_id]
    secondary_jobs = [j for j in report["jobs"] if j["job_id"] != primary_id]

    share_strings: List[Tuple[str, str]] = []  # (where, text) —— 分享面（卡片 + 发布文案）
    report_strings: List[Tuple[str, str]] = []  # 报告面

    # 2. 首屏
    verdict = ed.get("verdict", {})
    if not verdict.get("heading"):
        err("verdict.heading 必填：首屏大标题直接回答「怎么投」")
    for seg in verdict.get("heading", []):
        report_strings.append(("verdict.heading", seg.get("t", "")))
    report_strings.append(("verdict.prose", verdict.get("prose", "")))
    share_strings.append(("verdict.heading", "".join(s.get("t", "") for s in verdict.get("heading", []))))
    share_strings.append(("verdict.prose", verdict.get("prose", "")))

    # 3. 岗位对比：每个岗位一条，注明归属
    comp = ed.get("comparison", [])
    comp_jobs = [c.get("job_id") for c in comp]
    for job in report["jobs"]:
        if job["job_id"] not in comp_jobs:
            err(f"comparison 缺少岗位 {job['job_id']}（{job['title']}）")
    for i, c in enumerate(comp):
        if c.get("job_id") not in jobs:
            err(f"comparison[{i}].job_id 无法解析: {c.get('job_id')!r}")
        report_strings.append((f"comparison[{i}].note", c.get("note", "")))
        share_strings.append((f"comparison[{i}].note", c.get("note", "")))

    # 4. 关键发现：锚点可解析、放大镜逐字、条目简短版齐全
    findings = ed.get("findings", [])
    if not (1 <= len(findings) <= 4):
        err(f"findings 应为 1–4 条，实际 {len(findings)}")
    for i, f in enumerate(findings):
        w = f"findings[{i}]"
        for ev in f.get("evidence_ids", []):
            if ev not in evs:
                err(f"{w}.evidence_ids 无法解析 {ev}")
        _voice_lint(errors, f"{w}.title", f.get("title"))
        _voice_lint(errors, f"{w}.body", f.get("body"))
        report_strings.extend([(f"{w}.title", f.get("title", "")), (f"{w}.body", f.get("body", ""))])
        share_strings.extend([(f"{w}.title", f.get("title", "")), (f"{w}.body", f.get("body", "")),
                              (f"{w}.strip_label", f.get("strip_label", "")),
                              (f"{w}.strip_body", f.get("strip_body", ""))])
        loupe = f.get("loupe")
        if loupe:
            loupe_evs = loupe.get("evidence_ids", [])
            if not loupe_evs:
                err(f"{w}.loupe.evidence_ids 至少引用一条证据")
            quote_pool = []
            for ev in loupe_evs:
                if ev not in evs:
                    err(f"{w}.loupe.evidence_ids 无法解析 {ev}")
                else:
                    quote_pool.append(evs[ev]["quote"])
            raw = loupe.get("raw_line", "")
            if raw and quote_pool and not any(raw in q for q in quote_pool):
                err(f"{w}.loupe.raw_line 不是引用证据原文的连续子串（放大镜必须逐字）:\n    {raw}")
            hl = loupe.get("highlight", "")
            if hl and raw and hl not in raw:
                err(f"{w}.loupe.highlight 必须是 raw_line 的子串")
            _voice_lint(errors, f"{w}.loupe.annotation", loupe.get("annotation"))
            report_strings.append((f"{w}.loupe.annotation", loupe.get("annotation", "")))
            share_strings.append((f"{w}.loupe.raw_line", raw))
            share_strings.append((f"{w}.loupe.annotation", loupe.get("annotation", "")))

    # 5. 改写：ID 可解析、JD 锚点逐字、after 文本事实保真（数字逐个对 + 职责词零新增）
    ed_rewrites = ed.get("rewrites", [])
    effective_report_ids = {rid for rid, r in rws.items() if not r.get("pending_fill")}
    covered_ids = []
    for i, item in enumerate(ed_rewrites):
        w = f"rewrites[{i}]"
        rid = item.get("rewrite_id")
        covered_ids.append(rid)
        if rid not in rws:
            err(f"{w}.rewrite_id 无法解析: {rid!r}")
            continue
        rw = rws[rid]
        if rw.get("pending_fill"):
            err(f"{w}: 待补项（{rid}）不能进重点改写区")
        # JD 锚点：引号内一律 JD 原文（reviewer 顺延修正 b）
        anchor_req = item.get("jd_anchor_req")
        if anchor_req not in reqs:
            err(f"{w}.jd_anchor_req 无法解析: {anchor_req!r}")
        else:
            jd_quote = reqs[anchor_req].get("jd_quote", "")
            if item.get("jd_anchor") and item["jd_anchor"] not in jd_quote:
                err(f"{w}.jd_anchor 不是该要求 jd_quote 原文的连续子串:\n    {item['jd_anchor']}")
        before = item.get("before_text") or rw.get("original_quote", "")
        after = item.get("after_text") or rw.get("rewritten_text", "")
        if item.get("before_text") and item["before_text"] != rw.get("original_quote"):
            err(f"{w}.before_text 与报告 original_quote 不一致（改前原句以报告数据为准）")
        pool = before + " " + " ".join(evs[e]["quote"] for e in rw.get("numbers_from", []) if e in evs)
        pool_digits = set(_digits_of(pool))
        for num in _digits_of(after):
            if num not in pool_digits:
                err(f"{w}: 改写后数字「{num}」在改写前文本与引用证据中均无原样出处（数字逐个对）")
        for word in SCOPE_WORDS:
            if word in after and word not in before and word not in pool:
                err(f"{w}: 改写后新增职责范围词「{word}」——原句没有就不准出现")
        for s in item.get("strikes", []):
            if s and s not in before:
                err(f"{w}.strikes 子串「{s}」不在改前原句里")
        for h in item.get("highlights", []):
            if h and h not in after:
                err(f"{w}.highlights 子串「{h}」不在改写后文本里")
        _voice_lint(errors, f"{w}.annotation", item.get("annotation"))
        _voice_lint(errors, f"{w}.badge", item.get("badge"))
        report_strings.append((f"{w}.annotation", item.get("annotation", "")))
        share_strings.extend([(f"{w}.after_text", after), (f"{w}.annotation", item.get("annotation", ""))])
    missing_rw = effective_report_ids - set(covered_ids)
    if missing_rw:
        err(f"重点改写区缺少有效改写 {sorted(missing_rw)}（不凑数也不静默丢弃）")

    # 6. 行动：恰好覆盖报告的 3 项行动
    ed_acts = ed.get("actions", [])
    report_act_ids = {a["action_id"] for a in report["actions"]}
    covered_act = {a.get("action_id") for a in ed_acts}
    if covered_act != report_act_ids:
        err(f"actions 必须一一覆盖报告行动 {sorted(report_act_ids)}，实际 {sorted(covered_act)}")
    for i, a in enumerate(ed_acts):
        w = f"actions[{i}]"
        for field in ("title", "body", "deliverable", "criteria"):
            _voice_lint(errors, f"{w}.{field}", a.get(field))
            report_strings.append((f"{w}.{field}", a.get(field, "")))
            share_strings.extend([(f"{w}.title", a.get("title", "")), (f"{w}.body", a.get("body", ""))])
        for chip in a.get("chips", []):
            share_strings.append((f"{w}.chips", chip.get("text", "")))
    if ed.get("cards", {}).get("actions_card"):
        share_strings.append(("actions_card.takeaway", ed["cards"]["actions_card"].get("takeaway", "")))

    # 6.5 成员版分享卡内容组（0.2.0；与案例卡共用评分结果与证据，不另算分）
    if is_v2 and ed.get("member_card"):
        mc = ed["member_card"]
        m_findings = mc.get("findings", [])
        if not isinstance(m_findings, list) or not (2 <= len(m_findings) <= 3):
            err(f"member_card.findings 需要 2–3 条（优势与缺口并陈），实际 {len(m_findings) if isinstance(m_findings, list) else type(m_findings).__name__}")
        for i, f in enumerate(m_findings):
            w = f"member_card.findings[{i}]"
            if f.get("tone") not in ("advantage", "focus"):
                err(f"{w}.tone 必须是 advantage（优势）或 focus（缺口），实际 {f.get('tone')!r}")
            for field in ("badge", "lead", "text"):
                _voice_lint(errors, f"{w}.{field}", f.get(field))
                share_strings.append((f"{w}.{field}", f.get(field, "")))
        m_act = mc.get("action")
        if not isinstance(m_act, dict) or not m_act.get("text"):
            err("member_card.action 缺失：成员卡必须给一条下一步方向（低分也不羞辱用户或夸大优势）")
        else:
            for field in ("tag", "step_label", "lead", "text"):
                _voice_lint(errors, f"member_card.action.{field}", m_act.get(field))
                share_strings.append((f"member_card.action.{field}", m_act.get(field, "")))
        for field in ("kicker", "verdict_note"):
            if mc.get(field):
                _voice_lint(errors, f"member_card.{field}", mc.get(field))
                share_strings.append((f"member_card.{field}", mc.get(field, "")))

    # 7. 判定注解：主目标全量覆盖；多岗位时次目标也要全量（岗位切换页签）
    notes = ed.get("evidence_notes", [])
    note_ids = [n.get("req_id") for n in notes]
    for rid in primary_req_ids:
        if rid not in note_ids:
            err(f"evidence_notes 缺少主目标要求 {rid}（判定详情必须全量，缺注解不渲染内部口径）")
    for i, n in enumerate(notes):
        if n["req_id"] not in reqs:
            err(f"evidence_notes[{i}].req_id 无法解析: {n.get('req_id')!r}")
        _voice_lint(errors, f"evidence_notes[{i}].note", n.get("note"))
        report_strings.append((f"evidence_notes[{i}].note", n.get("note", "")))
        share_strings.append((f"evidence_notes[{i}].note", n.get("note", "")))
    gate_notes = ed.get("gate_notes", [])
    gate_note_ids = [g.get("gate_id") for g in gate_notes]
    for gid, gate in gates.items():
        if gid not in gate_note_ids:
            err(f"gate_notes 缺少门槛 {gid}（{gate['text']}）")
    for i, g in enumerate(gate_notes):
        if g.get("gate_id") not in gates:
            err(f"gate_notes[{i}].gate_id 无法解析: {g.get('gate_id')!r}")
        _voice_lint(errors, f"gate_notes[{i}].note", g.get("note"))
        report_strings.append((f"gate_notes[{i}].note", g.get("note", "")))
        share_strings.append((f"gate_notes[{i}].note", g.get("note", "")))
    if secondary_jobs:
        sec_note_ids = [n.get("req_id") for n in ed.get("secondary_notes", [])]
        for job in secondary_jobs:
            for rid, r in reqs.items():
                if r["job_id"] == job["job_id"] and rid not in sec_note_ids:
                    err(f"secondary_notes 缺少 {job['job_id']} 的要求 {rid}（岗位切换页签需全量）")
        for i, n in enumerate(ed.get("secondary_notes", [])):
            if n.get("req_id") not in reqs:
                err(f"secondary_notes[{i}].req_id 无法解析: {n.get('req_id')!r}")
            elif reqs[n["req_id"]]["job_id"] == primary_id:
                err(f"secondary_notes[{i}] 指向主目标要求（应放 evidence_notes）")
            _voice_lint(errors, f"secondary_notes[{i}].note", n.get("note"))
            report_strings.append((f"secondary_notes[{i}].note", n.get("note", "")))

    if ed.get("pending_fill_note"):
        report_strings.append(("pending_fill_note", ed["pending_fill_note"]))
        share_strings.append(("pending_fill_note", ed["pending_fill_note"]))
    if ed.get("variant_note"):
        report_strings.append(("variant_note", ed["variant_note"]))
        share_strings.append(("variant_note", ed["variant_note"]))

    # 8. 卡片编排：封面 + 行动必须有；总量 1–6 张；每张标题段过纪律
    cards_cfg = ed.get("cards", {})
    enabled = [k for k in ("cover", "findings_card", "rewrites_card", "actions_card", "evidence_card") if cards_cfg.get(k)]
    fact_check_fields_later: List[Tuple[str, str]] = []  # 卡面标题（第 10 节并入溯源）
    if not cards_cfg.get("cover"):
        err("cards.cover 必须启用（封面诊断卡）")
    if not cards_cfg.get("actions_card"):
        err("cards.actions_card 必须启用（行动方法卡）")
    if not (1 <= len(enabled) <= 6):
        err(f"启用卡片数量应为 1–6，实际 {len(enabled)}")
    if cards_cfg.get("rewrites_card") and not ed_rewrites:
        err("rewrites_card 需要至少 1 条有效改写")
    if cards_cfg.get("findings_card") and not findings:
        err("findings_card 需要至少 1 条发现")
    if cards_cfg.get("evidence_card"):
        has_focus = any(n.get("focus") for n in notes)
        has_open_gate = any(gates[g]["status"] != "met" for g in gates)
        if not (has_focus or has_open_gate):
            err("evidence_card 需要至少 1 条重点判定注解或 1 条非通过门槛")
    for key in enabled:
        cfg = cards_cfg[key]
        for seg in cfg.get("headline", []):
            _voice_lint(errors, f"cards.{key}.headline", seg.get("t", ""))
            share_strings.append((f"cards.{key}.headline", seg.get("t", "")))
            # 行动卡标题是行动建议的导语（如「从 5 分钟问询到新版简历」），
            # 与行动正文同属建议类文本，不参与简历数字溯源；其余卡面标题照查。
            if key != "actions_card":
                fact_check_fields_later.append((f"cards.{key}.headline", seg.get("t", "")))
        _voice_lint(errors, f"cards.{key}.kicker", cfg.get("kicker"))
        share_strings.append((f"cards.{key}.kicker", cfg.get("kicker", "")))
    if cards_cfg.get("cover"):
        if not findings:
            err("cards.cover 需要发现条目（封面三大发现速览）")

    # 9. 发布文案：恰好 3 个标题、每条有结构化依据；合成案例必须标注
    social = ed.get("social", {})
    titles = social.get("titles", [])
    if len(titles) != 3:
        err(f"social.titles 必须恰好 3 条备选，实际 {len(titles)}")
    for i, t in enumerate(titles):
        _voice_lint(errors, f"social.titles[{i}].text", t.get("text"))
        basis = t.get("basis", {})
        if basis.get("finding") is not None and not (1 <= basis["finding"] <= len(findings)):
            err(f"social.titles[{i}].basis.finding 越界")
        if basis.get("rewrite") is not None and not (1 <= basis["rewrite"] <= len(ed_rewrites)):
            err(f"social.titles[{i}].basis.rewrite 越界")
        if basis.get("gate") is not None and basis["gate"] not in gates:
            err(f"social.titles[{i}].basis.gate 无法解析 {basis['gate']!r}")
        if basis.get("action") is not None and not (1 <= basis["action"] <= 3):
            err(f"social.titles[{i}].basis.action 越界")
        if not basis:
            err(f"social.titles[{i}] 缺少依据（每条标题必须指向一条证据）")
        share_strings.append((f"social.titles[{i}].text", t.get("text", "")))
    body = social.get("body_md", "")
    if not body:
        err("social.body_md 必填（发布正文）")
    _voice_lint(errors, "social.body_md", body)
    share_strings.append(("social.body_md", body))
    if report.get("synthetic") and "合成案例" not in body:
        err("social.body_md 必须注明「合成案例」（content-standards 3.3 匿名纪律）")
    # 编排自定义尾注同样上分享面：过表达纪律 + 隐私扫描（reviewer 观察项 1 收口）
    syn_note = social.get("synthetic_note", "")
    if syn_note:
        _voice_lint(errors, "social.synthetic_note", syn_note)
        share_strings.append(("social.synthetic_note", syn_note))

    # 10. 数字溯源：事实性文案里的数字必须落在证据池
    #     （简历原文 ∪ JD 原文 ∪ 追问回答 ∪ 岗位/变体分数 ∪ 改写前后文本）。
    #     行动建议类文本（actions 的 goal 类指导语）不含简历事实断言，不参与数字溯源。
    fact_pool_items = [e["quote"] for e in report["evidence"]]
    fact_pool_items += [r.get("jd_quote", "") for r in report["requirements"]]
    fact_pool_items += [g.get("jd_quote", "") for g in gates.values()]
    fact_pool_items += [a.get("answer", "") for a in report.get("answers", [])]
    fact_pool_items += [str(j.get("score")) for j in report["jobs"]]
    for var in report.get("answer_variants", []):
        fact_pool_items += [str(s) for s in var.get("job_scores", {}).values()]
    for item in ed_rewrites:
        rid = item.get("rewrite_id")
        if rid in rws and not rws[rid].get("pending_fill"):
            fact_pool_items.append(rws[rid].get("original_quote", ""))
            fact_pool_items.append(item.get("after_text") or rws[rid].get("rewritten_text", ""))
    pool_digits = set(_digits_of(" ".join(fact_pool_items)))

    fact_check_fields = [("verdict.prose", verdict.get("prose", ""))]
    fact_check_fields.extend(fact_check_fields_later)
    for i, f in enumerate(findings):
        fact_check_fields.append((f"findings[{i}].title", f.get("title", "")))
        fact_check_fields.append((f"findings[{i}].strip_body", f.get("strip_body", "")))
    for i, c in enumerate(comp):
        fact_check_fields.append((f"comparison[{i}].note", c.get("note", "")))
    for i, n in enumerate(notes):
        fact_check_fields.append((f"evidence_notes[{i}].note", n.get("note", "")))
    for i, g in enumerate(gate_notes):
        fact_check_fields.append((f"gate_notes[{i}].note", g.get("note", "")))
    for i, n in enumerate(ed.get("secondary_notes", [])):
        fact_check_fields.append((f"secondary_notes[{i}].note", n.get("note", "")))
    for i, a in enumerate(ed_acts):
        fact_check_fields.append((f"actions[{i}].template", a.get("template", "")))
        for chip in a.get("chips", []):
            fact_check_fields.append((f"actions[{i}].chips", chip.get("text", "")))
    if ed.get("pending_fill_note"):
        fact_check_fields.append(("pending_fill_note", ed["pending_fill_note"]))
    if ed.get("variant_note"):
        fact_check_fields.append(("variant_note", ed["variant_note"]))
    for i, t in enumerate(titles):
        fact_check_fields.append((f"social.titles[{i}].text", t.get("text", "")))
    fact_check_fields.append(("social.body_md", body))
    for i, f in enumerate(ed.get("member_card", {}).get("findings", [])):
        fact_check_fields.append((f"member_card.findings[{i}].lead", f.get("lead", "")))
        fact_check_fields.append((f"member_card.findings[{i}].text", f.get("text", "")))
    m_act = ed.get("member_card", {}).get("action")
    if isinstance(m_act, dict):
        fact_check_fields.append(("member_card.action.lead", m_act.get("lead", "")))
        fact_check_fields.append(("member_card.action.text", m_act.get("text", "")))
    for where, text in fact_check_fields:
        for num in _digits_of(text):
            if num not in pool_digits:
                err(f"{where}: 数字「{num}」不在简历原文/JD 原文/追问回答/报告分数池内（句句有锚点，数字禁止无出处）")

    # 11. 脱敏：分享面全部字符串过 private_markers / 邮箱 / 手机号
    markers = report.get("private_markers", [])
    for where, text in share_strings:
        _privacy_lint(errors, f"分享面 {where}", text, markers)

    # 12. 报告面表达纪律（报告含证据详情，隐私口径同报告 JSON，但禁内部话）
    for where, text in report_strings:
        _voice_lint(errors, f"报告面 {where}", text)

    return errors

# ---------------------------------------------------------------------------
# 设计系统：编辑批注风（视觉契约 = docs/mockup/ 定稿小样，MYW-69 用户已确认）
# ---------------------------------------------------------------------------

REPORT_CSS = """
:root{--paper-bg:#FBF9F5;--paper-card:#FFF;--paper-muted:#F5F2EA;--paper-highlight:#FFFDF0;
--ink-primary:#18181B;--ink-secondary:#52525B;--ink-tertiary:#71717A;--ink-border:#E5E1D5;--ink-border-subtle:#EFECE4;
--red-pen:#DC2626;--red-pen-dark:#B91C1C;--red-pen-bg:#FEF2F2;--red-pen-border:#FCA5A5;--red-pen-light:#FFF5F5;
--green-approved:#0F766E;--green-approved-bg:#F0FDF4;--green-approved-border:#86EFAC;
--amber:#B45309;--amber-bg:#FEF3C7;--amber-border:#FDE68A;
--font-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
--font-mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper-bg);color:var(--ink-primary);font-family:var(--font-sans);line-height:1.65;
-webkit-font-smoothing:antialiased;padding:32px 20px 80px;font-size:15px}
.editorial-wrapper{max-width:980px;margin:0 auto}
.masthead{border-bottom:2.5px solid var(--ink-primary);padding-bottom:16px;margin-bottom:32px;display:flex;
justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px}
.masthead-meta{display:flex;flex-direction:column;gap:6px}
.masthead-brand{font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-secondary);
display:flex;align-items:center;gap:10px}
.masthead-brand .stamp{display:inline-block;padding:2px 8px;border:1.5px solid var(--red-pen);color:var(--red-pen);
font-weight:900;font-size:11px;letter-spacing:.05em;transform:rotate(-1.5deg);border-radius:3px;background:#FFF}
.masthead-title{font-size:26px;font-weight:900;color:var(--ink-primary);letter-spacing:-.02em}
.masthead-badge-group{display:flex;align-items:center;gap:8px;font-size:12px;flex-wrap:wrap}
.badge-pill{padding:4px 12px;border-radius:9999px;background:var(--paper-muted);border:1px solid var(--ink-border);
color:var(--ink-secondary);font-weight:600;white-space:nowrap}
.toc-bar{display:flex;gap:10px;margin-bottom:24px;overflow-x:auto;padding-bottom:4px}
.toc-link{font-size:13px;font-weight:700;color:var(--ink-secondary);text-decoration:none;background:#FFF;
border:1px solid var(--ink-border);padding:5px 14px;border-radius:6px;white-space:nowrap;transition:all .2s}
.toc-link:hover{border-color:var(--ink-primary);color:var(--ink-primary)}
.section-card{background:var(--paper-card);border:1.5px solid var(--ink-border);border-radius:10px;padding:30px 36px;
margin-bottom:28px;box-shadow:0 1px 3px rgba(0,0,0,.02),0 8px 20px rgba(24,24,27,.025);position:relative}
.section-tag-label{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:800;letter-spacing:.08em;
text-transform:uppercase;color:var(--ink-tertiary);margin-bottom:16px}
.section-tag-label .num{background:var(--ink-primary);color:#FFF;width:20px;height:20px;display:inline-flex;
align-items:center;justify-content:center;border-radius:50%;font-size:11px;font-weight:900}
.verdict-hero{display:grid;grid-template-columns:1fr auto;gap:28px;align-items:start;border-bottom:1px dashed var(--ink-border);
padding-bottom:24px;margin-bottom:20px}
.verdict-main-heading{font-size:34px;font-weight:900;color:var(--ink-primary);line-height:1.25;letter-spacing:-.02em;margin-bottom:16px}
.verdict-main-heading .accent-mark{background:linear-gradient(180deg,transparent 65%,rgba(220,38,38,.22) 65%);
padding:0 4px;color:var(--ink-primary)}
.verdict-summary-prose{font-size:16px;line-height:1.75;color:var(--ink-secondary)}
.verdict-summary-prose strong{color:var(--ink-primary);font-weight:700}
.verdict-chip{display:inline-block;margin-top:14px;padding:3px 12px;border-radius:6px;font-size:13px;font-weight:800;
background:var(--ink-primary);color:#FFF}
.score-meter-card{background:var(--paper-muted);border:1.5px solid var(--ink-border);border-radius:10px;padding:20px 24px;
min-width:170px;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:center}
.score-meter-label{font-size:11px;font-weight:800;color:var(--ink-tertiary);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.score-meter-num{font-size:58px;font-weight:900;line-height:1;color:var(--ink-primary);letter-spacing:-.04em}
.score-meter-disclaimer{font-size:11px;color:var(--ink-tertiary);margin-top:8px;line-height:1.35}
.comparison-strip{display:grid;grid-template-columns:1fr 1fr;gap:16px;background:var(--paper-muted);border-radius:8px;
padding:18px 22px;border:1px solid var(--ink-border-subtle)}
.comp-box{display:flex;flex-direction:column;gap:6px}
.comp-box-header{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.comp-title{font-size:15px;font-weight:800;color:var(--ink-primary)}
.comp-badge{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:800}
.comp-badge.primary{background:#DC2626;color:#FFF}
.comp-badge.secondary{background:#E4E4E7;color:#52525B}
.comp-detail{font-size:13.5px;color:var(--ink-secondary);line-height:1.55}
.findings-grid{display:grid;grid-template-columns:1fr;gap:18px}
.finding-card{background:var(--paper-muted);border:1.5px solid var(--ink-border);border-radius:8px;padding:20px 24px;
display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:start}
.finding-pin{width:32px;height:32px;background:var(--ink-primary);color:#FFF;font-size:14px;font-weight:900;border-radius:6px;
display:flex;align-items:center;justify-content:center}
.finding-pin.accent{background:var(--red-pen);box-shadow:0 2px 6px rgba(220,38,38,.25)}
.finding-content h4{font-size:17px;font-weight:800;color:var(--ink-primary);margin-bottom:6px;line-height:1.45}
.finding-content p{font-size:14.5px;color:var(--ink-secondary);line-height:1.6}
.loupe-box{margin-top:14px;background:#FFF;border:1.5px dashed var(--ink-border);border-left:4px solid var(--red-pen);
padding:14px 18px;border-radius:6px;font-size:14px}
.loupe-meta{font-size:12px;font-weight:800;color:var(--ink-tertiary);text-transform:uppercase;letter-spacing:.05em;
margin-bottom:6px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px}
.raw-line-wrap{background:#FAF8F5;padding:10px 14px;border-radius:6px;border:1px solid #EFECE4;font-family:var(--font-mono);
font-size:14px;line-height:1.6;color:var(--ink-secondary);word-break:break-word}
.loupe-red-circle{border:2px solid var(--red-pen);color:var(--red-pen-dark);font-weight:800;padding:1px 6px;border-radius:4px;
background:var(--red-pen-light);display:inline-block}
.red-pen-tag{display:flex;align-items:flex-start;gap:6px;color:var(--red-pen);font-weight:700;font-size:13px;
margin-top:8px;line-height:1.5}
.rewrite-item{border:1.5px solid var(--ink-border);border-radius:8px;margin-bottom:24px;background:#FFF;overflow:hidden;
box-shadow:0 2px 8px rgba(24,24,27,.02)}
.rewrite-header{background:var(--paper-muted);padding:14px 22px;border-bottom:1px solid var(--ink-border);display:flex;
justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}
.rewrite-title{font-size:15px;font-weight:800;color:var(--ink-primary);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rewrite-diff-body{padding:22px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
.diff-panel{border-radius:8px;padding:16px 18px;font-size:14.5px;line-height:1.65}
.diff-before{background:#FAF9F6;border:1.5px solid #E4E1D8;color:#71717A}
.diff-after{background:var(--green-approved-bg);border:1.5px solid var(--green-approved-border);color:#064E3B;font-weight:500}
.diff-label{font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px;
display:flex;align-items:center;gap:6px}
.diff-before .diff-label{color:#71717A}
.diff-after .diff-label{color:var(--green-approved)}
.diff-strike{text-decoration:line-through;text-decoration-color:var(--red-pen);text-decoration-thickness:2px;color:#A1A1AA}
.diff-key-fact{background:rgba(16,185,129,.18);color:#065F46;font-weight:800;padding:1px 6px;border-radius:4px}
.annotation-sticky{background:var(--red-pen-light);border-top:1.5px solid var(--red-pen-border);padding:16px 22px;
display:flex;gap:14px;align-items:flex-start}
.annotation-stamp{background:var(--red-pen);color:#FFF;font-size:11px;font-weight:900;padding:2px 8px;border-radius:4px;
white-space:nowrap;letter-spacing:.05em;margin-top:2px}
.annotation-body{font-size:14px;color:var(--red-pen-dark);line-height:1.65}
.annotation-body strong{font-weight:800;color:#7F1D1D}
.pending-box{border:1.5px dashed var(--amber-border);background:var(--amber-bg);border-radius:8px;padding:16px 22px;
display:flex;gap:14px;align-items:flex-start}
.pending-stamp{background:var(--amber);color:#FFF;font-size:11px;font-weight:900;padding:2px 8px;border-radius:4px;
white-space:nowrap;margin-top:2px}
.pending-body{font-size:14px;color:#78350F;line-height:1.65}
.actions-timeline{display:flex;flex-direction:column;gap:18px}
.action-step-card{border:1.5px solid var(--ink-border);border-radius:8px;padding:20px 24px;background:var(--paper-muted);
display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:start}
.action-step-badge{background:var(--ink-primary);color:#FFF;font-size:13px;font-weight:800;padding:4px 10px;
border-radius:6px;white-space:nowrap}
.action-step-badge.red{background:var(--red-pen)}
.action-step-body h4{font-size:16px;font-weight:800;color:var(--ink-primary);margin-bottom:8px;line-height:1.45}
.action-step-body>p{font-size:14px;color:var(--ink-secondary);line-height:1.6}
.action-meta-grid{display:grid;grid-template-columns:1fr;gap:10px;margin-top:12px;font-size:13.5px}
.action-meta-item{display:flex;flex-direction:column;gap:4px;background:#FFF;padding:10px 14px;border-radius:6px;
border:1px solid var(--ink-border-subtle)}
.action-meta-key{font-weight:800;color:var(--ink-tertiary);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.action-meta-val{color:var(--ink-primary);line-height:1.5}
.copy-box{display:flex;align-items:center;justify-content:space-between;gap:8px;background:#FAF8F5;padding:8px 12px;
border-radius:6px;border:1px dashed #DDD8CC;margin-top:4px}
.copy-snippet{font-family:var(--font-mono);font-size:13px;color:var(--ink-primary);word-break:break-all}
.copy-btn{font-size:12px;font-weight:700;padding:4px 10px;border-radius:6px;border:1px solid var(--ink-border);
background:#FFF;color:var(--ink-secondary);cursor:pointer;white-space:nowrap}
.copy-btn:hover{border-color:var(--ink-primary);color:var(--ink-primary)}
.check-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.chip{background:#FFF;border:1.5px solid #D4CEBE;padding:4px 12px;border-radius:6px;font-size:13px;font-weight:700;color:#27272A}
.chip.highlight{border-color:var(--red-pen);color:var(--red-pen);background:var(--red-pen-light)}
.job-tabs{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}
.job-tab{font-size:14px;font-weight:800;padding:8px 18px;border-radius:8px;border:1.5px solid var(--ink-border);
background:#FFF;color:var(--ink-secondary);cursor:pointer}
.job-tab.active{background:var(--ink-primary);color:#FFF;border-color:var(--ink-primary)}
.job-tab .tab-score{font-size:12px;font-weight:900;margin-left:6px;opacity:.85}
.job-pane{display:none}
.job-pane.active{display:block}
.details-accordion{border:1.5px solid var(--ink-border);border-radius:8px;overflow:hidden;background:#FFF;margin-bottom:14px}
.details-summary{padding:16px 22px;background:var(--paper-muted);cursor:pointer;font-weight:800;font-size:15px;
display:flex;justify-content:space-between;align-items:center;user-select:none;border-bottom:1px solid var(--ink-border);
gap:10px;flex-wrap:wrap}
.details-summary:hover{background:#EFECE4}
.evidence-rule-card{border-left:4px solid var(--ink-primary);background:var(--paper-muted);padding:16px 18px;
border-radius:0 6px 6px 0;margin:14px 18px}
.evidence-rule-card.red{border-left-color:var(--red-pen)}
.evidence-rule-title{font-size:15px;font-weight:800;color:var(--ink-primary);margin-bottom:8px;display:flex;
justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.evidence-rule-text{font-size:14px;color:var(--ink-secondary);line-height:1.65}
.evidence-rule-text strong{color:var(--ink-primary)}
.status-pill{font-size:12px;padding:2px 10px;border-radius:4px;font-weight:800;white-space:nowrap}
.status-pill.green{color:var(--green-approved);background:var(--green-approved-bg);border:1px solid var(--green-approved-border)}
.status-pill.amber{color:var(--amber);background:var(--amber-bg);border:1px solid var(--amber-border)}
.status-pill.gray{color:var(--ink-secondary);background:var(--paper-muted);border:1px solid var(--ink-border)}
.status-pill.red{color:var(--red-pen);background:var(--red-pen-light);border:1px solid var(--red-pen-border)}
.evidence-location{font-size:12px;font-weight:700;color:var(--ink-tertiary);margin-top:10px;display:flex;gap:6px;align-items:center}
.evidence-quotes{margin-top:10px;display:flex;flex-direction:column;gap:8px}
.variant-note{border:1.5px dashed var(--ink-border);background:var(--paper-highlight);border-radius:8px;padding:14px 18px;
font-size:13.5px;color:var(--ink-secondary);line-height:1.65;margin:14px 18px}
.variant-note strong{color:var(--ink-primary)}
.report-footer{text-align:center;padding:28px 0 12px;font-size:13px;color:var(--ink-tertiary);
border-top:1.5px solid var(--ink-border);margin-top:36px;line-height:1.6}
@media (max-width:768px){
body{padding:16px 12px 64px}
.toc-bar{flex-wrap:wrap;gap:8px 10px;overflow-x:visible}
.toc-link{white-space:normal;padding:6px 12px;font-size:12px}
.masthead-title{font-size:22px}
.section-card{padding:20px 16px;margin-bottom:20px}
.verdict-hero{grid-template-columns:1fr;gap:16px}
.verdict-main-heading{font-size:26px}
.score-meter-card{width:100%;min-width:unset;flex-direction:row;justify-content:space-around;padding:14px}
.score-meter-num{font-size:44px}
.comparison-strip{grid-template-columns:1fr;gap:12px;padding:14px 16px}
.finding-card{grid-template-columns:1fr;gap:12px;padding:16px}
.finding-pin{width:28px;height:28px;font-size:12px}
.rewrite-diff-body{grid-template-columns:1fr;gap:12px;padding:16px}
.diff-panel{font-size:14px;padding:12px 14px}
.action-step-card{grid-template-columns:1fr;gap:12px;padding:16px}
.annotation-sticky{padding:14px 16px}
.evidence-rule-card{margin:14px 12px}
}
@media print{
body{padding:0;background:#FFF}
.toc-bar,.copy-btn,.job-tabs{display:none}
.section-card{box-shadow:none;break-inside:avoid}
.job-pane{display:block!important}
}
"""

CARD_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
.card-canvas{width:1080px;height:1440px;padding:56px 60px;display:flex;flex-direction:column;
justify-content:space-between;position:relative;background:#FBF9F5;overflow:hidden;
font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
color:#18181B;-webkit-font-smoothing:antialiased}
.header-bar{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #18181B;
padding-bottom:18px;flex-shrink:0}
.header-brand{font-size:18px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#52525B;
display:flex;align-items:center;gap:12px}
.header-stamp{border:2px solid #DC2626;color:#DC2626;padding:2px 10px;border-radius:4px;font-size:14px;font-weight:900;
letter-spacing:.08em;transform:rotate(-2deg);background:#FFF}
.header-page-num{font-size:16px;font-weight:800;color:#71717A;letter-spacing:.08em;background:#EFECE4;
padding:4px 14px;border-radius:999px}
.title-section{margin-top:6px;flex-shrink:0}
.kicker-tag{display:inline-block;font-size:18px;font-weight:800;color:#DC2626;letter-spacing:.06em;margin-bottom:12px;
background:#FEF2F2;border:1.5px solid #FCA5A5;padding:4px 14px;border-radius:6px}
.main-headline{font-size:52px;font-weight:900;line-height:1.25;letter-spacing:-.02em;color:#18181B}
.main-headline .highlight-red{color:#DC2626}
.main-headline .underline-marker{background:linear-gradient(180deg,transparent 65%,rgba(220,38,38,.2) 65%);padding:0 4px}
.loupe-container{background:#FFF;border:2px solid #E5E1D5;border-left:6px solid #DC2626;border-radius:12px;
padding:24px 30px;box-shadow:0 8px 24px rgba(24,24,27,.04);position:relative}
.loupe-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:10px;flex-wrap:wrap}
.loupe-header-title{font-size:16px;font-weight:800;color:#71717A;letter-spacing:.06em;text-transform:uppercase}
.loupe-badge{background:#FEF2F2;color:#DC2626;font-size:14px;font-weight:800;padding:2px 10px;border-radius:4px;
border:1px solid #FCA5A5}
.raw-resume-text{font-size:25px;color:#52525B;font-family:ui-monospace,Menlo,Consolas,monospace;line-height:1.5;
background:#FAF8F5;padding:16px 20px;border-radius:8px;border:1px dashed #DDD8CC;word-break:break-word}
.circle-burial{border:2.5px solid #DC2626;color:#DC2626;font-weight:900;padding:2px 8px;border-radius:6px;
background:#FFF5F5;display:inline-block}
.loupe-annotation{margin-top:14px;display:flex;align-items:flex-start;gap:12px;background:#FEF2F2;padding:14px 18px;
border-radius:8px;border:1px solid #FECACA}
.loupe-annotation-icon{background:#DC2626;color:#FFF;font-size:12px;font-weight:900;padding:2px 6px;border-radius:4px;
white-space:nowrap;margin-top:4px;flex-shrink:0}
.loupe-annotation-text{font-size:20px;font-weight:700;color:#991B1B;line-height:1.45}
.findings-strip{display:flex;flex-direction:column;gap:14px}
.finding-row{background:#FFF;border:1.5px solid #E5E1D5;border-radius:10px;padding:16px 24px;display:flex;
align-items:center;gap:18px}
.finding-idx{width:38px;height:38px;background:#18181B;color:#FFF;font-size:18px;font-weight:900;border-radius:8px;
display:flex;align-items:center;justify-content:center;flex-shrink:0}
.finding-idx.red{background:#DC2626}
.finding-body{font-size:22px;font-weight:700;color:#27272A;line-height:1.4}
.finding-body strong{color:#DC2626}
.verdict-banner{background:#18181B;color:#FFF;border-radius:12px;padding:22px 32px;display:flex;
justify-content:space-between;align-items:center;gap:20px}
.verdict-banner-left h3{font-size:27px;font-weight:900;color:#FFF;margin-bottom:4px;line-height:1.3}
.verdict-banner-left p{font-size:15px;color:#A1A1AA;line-height:1.4}
.verdict-banner-score{text-align:right;border-left:2px solid #3F3F46;padding-left:28px;flex-shrink:0}
.verdict-score-num{font-size:52px;font-weight:900;line-height:1;color:#FFF;letter-spacing:-.04em}
.verdict-score-desc{font-size:13px;color:#A1A1AA;margin-top:4px}
.footer-bar{border-top:1.5px solid #E5E1D5;padding-top:14px;display:flex;justify-content:space-between;
font-size:14px;color:#71717A;gap:12px;flex-shrink:0}
.diff-list{display:flex;flex-direction:column;gap:18px}
.diff-card{background:#FFF;border:2px solid #E5E1D5;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(24,24,27,.03)}
.diff-card-header{background:#F5F2EA;padding:10px 18px;border-bottom:1px solid #E5E1D5;display:flex;
justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.diff-card-title{font-size:18px;font-weight:800;color:#18181B}
.diff-card-tag{font-size:13px;font-weight:800;padding:3px 10px;border-radius:4px;background:#FFF;
border:1px solid #D4CEBE;color:#52525B}
.diff-card-tag.alert{color:#DC2626;border-color:#FCA5A5;background:#FEF2F2}
.diff-card-tag.good{color:#059669;border-color:#86EFAC;background:#F0FDF4}
.diff-card-body{padding:16px 20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
.diff-box{border-radius:8px;padding:12px 16px;font-size:16.5px;line-height:1.55}
.diff-box.before{background:#FAF9F6;border:1.5px solid #E4E1D8;color:#71717A}
.diff-box.after{background:#F0FDF4;border:1.5px solid #86EFAC;color:#064E3B;font-weight:600}
.diff-box-label{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.diff-box.before .diff-box-label{color:#A1A1AA}
.diff-box.after .diff-box-label{color:#059669}
.strike-text{text-decoration:line-through;text-decoration-color:#DC2626;text-decoration-thickness:2px;color:#A1A1AA}
.green-badge{background:rgba(16,185,129,.18);color:#065F46;padding:1px 6px;border-radius:4px;font-weight:800}
.diff-annotation{background:#FEF2F2;border-top:1.5px solid #FECACA;padding:10px 18px;display:flex;
align-items:flex-start;gap:10px}
.diff-annotation-stamp{background:#DC2626;color:#FFF;font-size:12px;font-weight:900;padding:2px 8px;border-radius:4px;
white-space:nowrap;margin-top:2px;flex-shrink:0}
.diff-annotation-text{font-size:20px;color:#991B1B;line-height:1.5;font-weight:600}
.diff-annotation-text strong{font-weight:800;color:#7F1D1D}
.principles-box{background:#18181B;color:#FFF;border-radius:12px;padding:14px 22px}
.principles-title{font-size:17px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#F87171;
margin-bottom:8px;display:flex;align-items:center;gap:8px}
.principles-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;font-size:18px;color:#E4E4E7;font-weight:600}
.principle-item{display:flex;align-items:center;gap:6px;line-height:1.35}
.principle-item::before{content:"✓";color:#4ADE80;font-weight:900}
.actions-list{display:flex;flex-direction:column;gap:18px}
.action-card{background:#FFF;border:2px solid #E5E1D5;border-radius:12px;padding:20px 28px;
box-shadow:0 4px 16px rgba(24,24,27,.03);position:relative}
.action-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px;flex-wrap:wrap}
.action-step-num{background:#18181B;color:#FFF;font-size:14px;font-weight:800;padding:4px 12px;border-radius:6px;letter-spacing:.04em}
.action-step-num.primary{background:#DC2626}
.action-timing-tag{font-size:14px;font-weight:800;color:#71717A;background:#F5F2EA;padding:3px 10px;border-radius:4px}
.action-card-title{font-size:23px;font-weight:900;color:#18181B;line-height:1.35;margin-bottom:10px}
.action-card-desc{font-size:17px;color:#52525B;line-height:1.55;margin-bottom:12px}
.template-box{background:#FAF8F5;border:1.5px dashed #DDD8CC;border-left:4px solid #DC2626;border-radius:6px;
padding:12px 18px;font-size:17px;color:#18181B;line-height:1.5}
.template-box.green{border-left-color:#059669;background:#F0FDF4;border-color:#BBF7D0}
.template-label{font-size:12px;font-weight:800;color:#71717A;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.template-content{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:18px;font-weight:700;color:#18181B}
.check-chips-card{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.chip-card{background:#FFF;border:1.5px solid #D4CEBE;padding:4px 12px;border-radius:6px;font-size:15px;font-weight:700;color:#27272A}
.chip-card.highlight{border-color:#DC2626;color:#DC2626;background:#FEF2F2}
.bottom-takeaway-banner{background:#18181B;color:#FFF;border-radius:12px;padding:22px 30px;display:flex;
align-items:center;gap:20px}
.takeaway-icon{font-size:32px;color:#F87171;flex-shrink:0}
.takeaway-text{font-size:18px;line-height:1.55;color:#E4E4E7}
.takeaway-text strong{color:#FFF;font-weight:800}
.judge-card{background:#FFF;border:2px solid #E5E1D5;border-radius:12px;padding:20px 26px}
.judge-card-header{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.judge-card-title{font-size:20px;font-weight:900;color:#18181B;line-height:1.35}
.judge-card-text{font-size:17px;color:#52525B;line-height:1.55}
.judge-card-text strong{color:#18181B}
.judge-source{font-size:13px;font-weight:700;color:#71717A;margin-top:10px}
/* 发现透视卡紧凑变体（三张判定卡 + 放大镜并排时的密度控制） */
.findings-list-tight{display:flex;flex-direction:column;gap:12px}
.findings-list-tight .judge-card{padding:14px 20px}
.findings-list-tight .judge-card-title{font-size:19px;line-height:1.3}
.findings-list-tight .judge-card-text{font-size:16px;line-height:1.5}
.findings-list-tight .loupe-container{padding:14px 18px;margin-top:10px;border-radius:10px}
.findings-list-tight .loupe-header{margin-bottom:8px}
.findings-list-tight .raw-resume-text{font-size:20px;padding:10px 14px}
.findings-list-tight .loupe-annotation{padding:10px 14px;margin-top:10px}
.findings-list-tight .loupe-annotation-text{font-size:18px}
"""

# ---------------------------------------------------------------------------
# 报告渲染（阅读顺序：结论 → 关键发现 → 改写 → 行动 → 证据详情）
# ---------------------------------------------------------------------------

REPORT_JS = """
(function(){
  function flash(btn, ok){ var old = btn.textContent; btn.textContent = ok ? '已复制 ✓' : '复制失败';
    setTimeout(function(){ btn.textContent = old; }, 1400); }
  document.addEventListener('click', function(e){
    var btn = e.target.closest('[data-copy]');
    if (!btn) return;
    var src = document.getElementById(btn.getAttribute('data-copy'));
    if (!src) return;
    var text = src.textContent;
    function fallback(){ var ta = document.createElement('textarea'); ta.value = text;
      ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select();
      var ok = false; try { ok = document.execCommand('copy'); } catch(err){ ok = false; }
      document.body.removeChild(ta); flash(btn, ok); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function(){ flash(btn, true); }, fallback);
    } else { fallback(); }
  });
  window.showJobPane = function(id){
    document.querySelectorAll('.job-tab').forEach(function(t){
      t.classList.toggle('active', t.getAttribute('data-pane') === id); });
    document.querySelectorAll('.job-pane').forEach(function(p){
      p.classList.toggle('active', p.id === id); });
  };
})();
"""


def _status_pill(status: str, kind: str) -> str:
    label, tone = (REQ_STATUS_HUMAN if kind == "req" else GATE_STATUS_HUMAN)[status]
    return f'<span class="status-pill {tone}">判定：{esc(label)}</span>'


def _render_report_module1(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    verdict = ed["verdict"]
    heading = seg_html(verdict["heading"])
    suggestion = SUGGESTION_HUMAN[job["suggestion"]]
    comp_boxes = []
    for comp in ed["comparison"]:
        cj = next((j for j in report["jobs"] if j["job_id"] == comp["job_id"]), None)
        score = cj["score"] if cj else "--"
        badge_cls = "primary" if comp.get("badge_type") == "primary" else "secondary"
        comp_boxes.append(
            f'<div class="comp-box"><div class="comp-box-header">'
            f'<span class="comp-badge {badge_cls}">{esc(comp.get("badge", "岗位"))}</span>'
            f'<span class="comp-title">{esc(comp.get("title", cj["title"] if cj else ""))} · {esc(score)} 分</span>'
            f'</div><div class="comp-detail">{md_bold(comp.get("note", ""))}</div></div>')
    return f"""
  <section class="section-card" id="section-verdict">
    <div class="section-tag-label"><span class="num">1</span> 审校结论 · Recommendation</div>
    <div class="verdict-hero">
      <div class="verdict-left">
        <h2 class="verdict-main-heading"><span class="accent-mark">{heading}</span></h2>
        <div class="verdict-summary-prose">{md_bold(verdict.get("prose", ""))}</div>
        <span class="verdict-chip">投递姿势：{esc(suggestion)}</span>
      </div>
      <div class="score-meter-card">
        <div class="score-meter-label">岗位证据覆盖分</div>
        <div class="score-meter-num">{esc(job["score"])}</div>
        <div class="score-meter-disclaimer">衡量材料对 JD 要求的覆盖度<br>不等于录取概率</div>
      </div>
    </div>
    <div class="comparison-strip">{''.join(comp_boxes)}</div>
  </section>"""


def _render_report_module2(ed: Dict[str, Any]) -> str:
    cards = []
    for i, f in enumerate(ed["findings"]):
        pin_cls = "accent" if i == 0 and f.get("pin_accent", i == 0) else ""
        loupe = ""
        if f.get("loupe"):
            lp = f["loupe"]
            raw = lp["raw_line"].replace(lp.get("highlight", ""), f'<span class="loupe-red-circle">{esc(lp["highlight"])}</span>', 1) if lp.get("highlight") else esc(lp["raw_line"])
            loupe = f"""
        <div class="loupe-box">
          <div class="loupe-meta"><span>简历原文检视（{esc(lp.get("source_label", "简历原文"))}）</span>
          <span style="color:var(--red-pen);font-weight:800;">[ {esc(lp.get("highlight_label", "痛点聚焦"))} ]</span></div>
          <div class="raw-line-wrap">{raw}</div>
          <div class="red-pen-tag"><span>↳</span><span>编辑部批注：{md_bold(lp.get("annotation", ""))}</span></div>
        </div>"""
        cards.append(f"""
      <div class="finding-card">
        <div class="finding-pin {pin_cls}">{i + 1:02d}</div>
        <div class="finding-content">
          <h4>{esc(f["title"])}</h4>
          <p>{md_bold(f.get("body", ""))}</p>{loupe}
        </div>
      </div>""")
    return f"""
  <section class="section-card" id="section-findings">
    <div class="section-tag-label"><span class="num">2</span> 关键发现与痛点透视 · Headline Findings</div>
    <div class="findings-grid">{''.join(cards)}</div>
  </section>"""


def _render_report_module3(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    reds = _build_redactions(ed)
    reqs = {r["req_id"]: r for r in report["requirements"]}
    items = []
    for i, item in enumerate(ed["rewrites"]):
        rw = next((r for r in report["rewrites"] if r["rewrite_id"] == item["rewrite_id"]), None)
        if rw is None:
            continue
        before = item.get("before_text") or rw.get("original_quote", "")
        after = item.get("after_text") or rw.get("rewritten_text", "")
        before, after = _redact(before, reds), _redact(after, reds)
        for s in item.get("strikes", []):
            before = before.replace(s, f'<span class="diff-strike">{esc(s)}</span>', 1)
        for h in item.get("highlights", []):
            after = after.replace(h, f'<span class="diff-key-fact">{esc(h)}</span>', 1)
        tone = {"red": 'style="color:var(--red-pen);border-color:var(--red-pen-border);background:var(--red-pen-light);"',
                "green": 'style="color:var(--green-approved);border-color:var(--green-approved-border);background:var(--green-approved-bg);"',
                "neutral": ""}.get(item.get("badge_tone", ""), "")
        anchor_req = reqs.get(item.get("jd_anchor_req"), {})
        items.append(f"""
    <div class="rewrite-item">
      <div class="rewrite-header">
        <div class="rewrite-title"><span>改写 {i + 1:02d} · {esc(item.get("label", ""))}</span>
        <span style="font-size:12.5px;font-weight:600;color:var(--ink-tertiary);">对齐 JD「{esc(item.get("jd_anchor", ""))}」</span></div>
        <span class="badge-pill" {tone}>{esc(item.get("badge", ""))}</span>
      </div>
      <div class="rewrite-diff-body">
        <div class="diff-panel diff-before"><div class="diff-label">改前原句{esc('（' + item['before_note'] + '）') if item.get('before_note') else ''}</div>{before}</div>
        <div class="diff-panel diff-after"><div class="diff-label">{esc(item.get("after_label", "改后定稿"))}</div>{after}</div>
      </div>
      <div class="annotation-sticky"><span class="annotation-stamp">编辑部批注</span>
        <div class="annotation-body">{md_bold(item.get("annotation", ""))}</div></div>
    </div>""")
    pending = [r for r in report["rewrites"] if r.get("pending_fill")]
    pending_html = ""
    if pending:
        rows = "".join(
            f'<div style="margin-top:8px;"><strong>{esc(r.get("target_gap", ""))}</strong>：{esc(r.get("ask", ""))}</div>'
            for r in pending)
        pending_html = f"""
    <div class="pending-box"><span class="pending-stamp">改不了的部分</span>
      <div class="pending-body">{md_bold(ed.get("pending_fill_note", "以下缺口改写无能为力，需要补事实："))}{rows}</div></div>"""
    return f"""
  <section class="section-card" id="section-rewrites">
    <div class="section-tag-label"><span class="num">3</span> 重点改写区 · 局部精准优化</div>
    {''.join(items)}{pending_html}
  </section>"""


def _render_report_module4(ed: Dict[str, Any]) -> str:
    steps = []
    for i, a in enumerate(ed["actions"]):
        copy_box = ""
        if a.get("template"):
            cid = f"copy-act-box-{i + 1}"
            copy_box = (f'<div class="copy-box"><span class="copy-snippet" id="{cid}">{esc(a["template"])}</span>'
                        f'<button class="copy-btn" data-copy="{cid}">复制</button></div>')
        chips = ""
        if a.get("chips"):
            chip_html = "".join(
                f'<span class="chip {"highlight" if c.get("highlight") else ""}">{esc(c["text"])}</span>'
                for c in a["chips"])
            chips = f'<div class="check-chips">{chip_html}</div>'
        badge_cls = "red" if a.get("badge_tone") == "red" else ""
        steps.append(f"""
      <div class="action-step-card">
        <div class="action-step-badge {badge_cls}">{esc(a.get("badge", f"第 {i + 1} 步"))}</div>
        <div class="action-step-body">
          <h4>{esc(a["title"])}</h4>
          <p>{md_bold(a.get("body", ""))}</p>
          <div class="action-meta-grid">
            <div class="action-meta-item"><span class="action-meta-key">{esc(a.get("deliverable_label", "交付成果"))}</span>
              <span class="action-meta-val">{md_bold(a.get("deliverable", ""))}</span>{copy_box}</div>
            <div class="action-meta-item"><span class="action-meta-key">{esc(a.get("criteria_label", "完成标准"))}</span>
              <span class="action-meta-val">{md_bold(a.get("criteria", ""))}</span></div>
          </div>{chips}
        </div>
      </div>""")
    return f"""
  <section class="section-card" id="section-actions">
    <div class="section-tag-label"><span class="num">4</span> 行动清单 · Action Plan</div>
    <div class="actions-timeline">{''.join(steps)}</div>
  </section>"""


def _render_report_module5(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    reds = _build_redactions(ed)
    sources = {s["source_id"]: s for s in report["sources"]}
    evs = {e["evidence_id"]: e for e in report["evidence"]}
    answers = {a["answer_id"]: a for a in report.get("answers", [])}
    jobs_by_id = {j["job_id"]: j for j in report["jobs"]}

    def req_card(rid: str, note: str, focus: bool, note_map_prefix: str) -> str:
        r = next(x for x in report["requirements"] if x["req_id"] == rid)
        quotes = []
        for eid in r.get("evidence_ids", []):
            ev = evs.get(eid)
            if ev:
                kind = sources.get(ev["source_id"], {}).get("kind", "resume")
                quotes.append(f'<div class="raw-line-wrap">{esc(_redact(ev["quote"], reds))}<div class="evidence-location">出处：{esc(human_locator(ev["locator"], kind))}</div></div>')
        for aid in r.get("answer_ids", []):
            an = answers.get(aid)
            if an:
                quotes.append(f'<div class="raw-line-wrap" style="border-color:#FDE68A;background:#FFFBF0;">追问补充：{esc(_redact(an["answer"], reds))}</div>')
        quotes_html = f'<div class="evidence-quotes">{"".join(quotes)}</div>' if quotes else ""
        jd_loc = human_locator(r.get("locator", ""), "jd")
        return f"""
      <details class="details-accordion"{' open' if focus else ''}>
        <summary class="details-summary"><span>{esc(r["text"])}<span style="font-size:12px;font-weight:600;color:var(--ink-tertiary);margin-left:8px;">（{esc(IMPORTANCE_HUMAN.get(r["importance"], ""))}）</span></span>
        <span style="font-size:12.5px;color:var(--ink-tertiary);">▾ 展开/折叠</span></summary>
        <div class="details-content" style="padding:0;">
          <div class="evidence-rule-card {'red' if r['status'] == 'unmet' else ''}">
            <div class="evidence-rule-title"><span>{_status_pill(r["status"], "req")}</span></div>
            <div class="evidence-rule-text">{md_bold(note)}</div>
            <div class="evidence-location">出处定位：{esc(jd_loc)}</div>{quotes_html}
          </div>
        </div>
      </details>"""

    def gate_cards(job_id: str) -> str:
        job = jobs_by_id[job_id]
        cards = []
        for g in job.get("gates", []):
            note = next((n["note"] for n in ed.get("gate_notes", []) if n["gate_id"] == g["gate_id"]), "")
            cards.append(f"""
      <div class="evidence-rule-card {'red' if g['status'] != 'met' else ''}">
        <div class="evidence-rule-title"><span>硬性门槛：{esc(g["text"])}</span>{_status_pill(g["status"], "gate")}</div>
        <div class="evidence-rule-text">{md_bold(note)}</div>
      </div>""")
        return "".join(cards)

    panes = []
    tabs = []
    for idx, job in enumerate(report["jobs"]):
        is_primary = job["job_id"] == report["primary_job_id"]
        pane_id = f"job-pane-{job['job_id']}"
        active = "active" if idx == 0 else ""
        note_key = "evidence_notes" if is_primary else "secondary_notes"
        notes = ed.get(note_key, [])
        cards = "".join(req_card(n["req_id"], n.get("note", ""), bool(n.get("focus")), note_key) for n in notes)
        variant_html = ""
        if is_primary and ed.get("variant_note") and report.get("answer_variants"):
            variant_html = f'<div class="variant-note"><strong>追问补充事实 · 重跑口径</strong>：{md_bold(ed["variant_note"])}</div>'
        panes.append(f'<div class="job-pane {active}" id="{pane_id}">{gate_cards(job["job_id"])}{cards}{variant_html}</div>')
        tabs.append(f'<button class="job-tab {active}" data-pane="{pane_id}" onclick="showJobPane(\'{pane_id}\')">'
                    f'{esc(job["title"])}<span class="tab-score">{esc(job["score"])} 分</span></button>')
    return f"""
  <section class="section-card" id="section-evidence">
    <div class="section-tag-label"><span class="num">5</span> 证据详情与判定理由 · Evidence Details</div>
    <div class="job-tabs">{''.join(tabs)}</div>
    {''.join(panes)}
  </section>"""


def render_editorial_report(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    """渲染编辑批注风自包含互动报告 HTML（数据 + 编排已通过 validate_editorial）。"""
    case_label = esc(ed.get("masthead", {}).get("case_label", report.get("case_id", "")))
    synthetic_badge = '<span class="badge-pill">脱敏合成案例</span>' if report.get("synthetic") else '<span class="badge-pill">已脱敏</span>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>岗位匹配深度审校报告 · {esc(ed.get("masthead", {}).get("case_label", report.get("case_id", "")))}</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<div class="editorial-wrapper">
  <header class="masthead">
    <div class="masthead-meta">
      <div class="masthead-brand">RESUME EDITORIAL AUDIT <span class="stamp">编辑部审校定稿</span></div>
      <h1 class="masthead-title">{esc(ed.get("masthead", {}).get("title", "岗位匹配深度诊断与改写"))}</h1>
    </div>
    <div class="masthead-badge-group"><span class="badge-pill">案例：{case_label}</span>{synthetic_badge}</div>
  </header>
  <nav class="toc-bar">
    <a href="#section-verdict" class="toc-link">1. 审校结论</a>
    <a href="#section-findings" class="toc-link">2. 关键发现</a>
    <a href="#section-rewrites" class="toc-link">3. 重点改写区</a>
    <a href="#section-actions" class="toc-link">4. 行动清单</a>
    <a href="#section-evidence" class="toc-link">5. 证据详情</a>
  </nav>
{_render_report_module1(report, ed)}
{_render_report_module2(ed)}
{_render_report_module3(report, ed)}
{_render_report_module4(ed)}
{_render_report_module5(report, ed)}
  <footer class="report-footer">
    <div>分数 = 简历证据对该 JD 要求的覆盖度，不代表能力总分或录取概率 · 案例已脱敏</div>
    <div style="margin-top:4px;color:#A1A1AA;">求职体检与深度匹配报告 · 编辑部审校定稿</div>
  </footer>
</div>
<script>{REPORT_JS}</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# 卡片渲染（1080×1440；预览与 PNG 导出共用同一卡片 DOM —— 零样式漂移）
# ---------------------------------------------------------------------------

PRINCIPLES_ITEMS = ["数字逐个对，原样出处", "职责范围词零新增", "集体归属不变成「我」",
                    "不跨经历合并拼凑", "只动结构绝不动事实", "改句子不会让匹配分上涨"]


def _card_shell(page_num: int, total: int, page_label: str, body_html: str, case_tag: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Card {page_num:02d} · {esc(page_label)} (1080x1440)</title>
<style>{CARD_CSS}</style></head>
<body>
<div class="card-canvas">
  <div class="header-bar">
    <div class="header-brand">RESUME FIT AUDIT <span class="header-stamp">编辑部审校定稿</span></div>
    <div class="header-page-num">CARD {page_num:02d} / {total:02d} · {esc(page_label)}</div>
  </div>
{body_html}
  <div class="footer-bar">
    <span>分数 = 简历证据对 JD 的覆盖度，不代表录取概率</span>
    <span>脱敏合成案例 · {esc(case_tag)}</span>
  </div>
</div>
</body>
</html>"""


def _card_headline(cfg: Dict[str, Any]) -> str:
    kicker = f'<div class="kicker-tag">{esc(cfg.get("kicker", ""))}</div>' if cfg.get("kicker") else ""
    return f'<div class="title-section">{kicker}<h1 class="main-headline">{seg_html(cfg.get("headline", []))}</h1></div>'


def _card_loupe(loupe: Dict[str, Any]) -> str:
    raw = loupe["raw_line"]
    hl = loupe.get("highlight", "")
    raw_html = raw.replace(hl, f'<span class="circle-burial">{esc(hl)}</span>', 1) if hl else esc(raw)
    return f"""
  <div class="loupe-container">
    <div class="loupe-header"><span class="loupe-header-title">{esc(loupe.get("source_label", "简历原句切片"))}</span>
    <span class="loupe-badge">{esc(loupe.get("highlight_label", "痛点聚焦"))}</span></div>
    <div class="raw-resume-text">{raw_html}</div>
    <div class="loupe-annotation"><div class="loupe-annotation-icon">红笔批注</div>
    <div class="loupe-annotation-text">{md_bold(loupe.get("annotation", ""))}</div></div>
  </div>"""


def _card_cover(report: Dict[str, Any], ed: Dict[str, Any], page_num: int, total: int) -> str:
    cfg = ed["cards"]["cover"]
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    loupe = next((f["loupe"] for f in ed["findings"] if f.get("loupe")), None)
    loupe_html = _card_loupe(loupe) if loupe else ""
    strip = "".join(
        f'<div class="finding-row"><div class="finding-idx {"red" if i == 0 else ""}">{i + 1:02d}</div>'
        f'<div class="finding-body"><strong>{esc(f.get("strip_label", ""))}：</strong>{esc(f.get("strip_body", ""))}</div></div>'
        for i, f in enumerate(ed["findings"][:3]))
    heading_text = "".join(s.get("t", "") for s in ed["verdict"]["heading"])
    body = f"""
  {_card_headline(cfg)}
{loupe_html}
  <div class="findings-strip">{strip}</div>
  <div class="verdict-banner">
    <div class="verdict-banner-left"><h3>【{esc(heading_text)}】</h3>
    <p>{esc(cfg.get("banner_sub", "改句子不涨匹配分，但决定招聘方 10 秒内能不能看到事实"))}</p></div>
    <div class="verdict-banner-score"><div class="verdict-score-num">{esc(job["score"])}</div>
    <div class="verdict-score-desc">岗位证据覆盖分</div></div>
  </div>"""
    return _card_shell(page_num, total, cfg.get("page_label", "封面诊断"), body, ed.get("case_tag", "CASE"))


def _card_findings(report: Dict[str, Any], ed: Dict[str, Any], page_num: int, total: int) -> str:
    cfg = ed["cards"]["findings_card"]
    rows = []
    for i, f in enumerate(ed["findings"]):
        loupe_html = _card_loupe(f["loupe"]) if f.get("loupe") else ""
        rows.append(f"""
  <div class="judge-card">
    <div class="judge-card-header"><span class="action-step-num {"primary" if i == 0 else ""}">发现 {i + 1:02d}</span></div>
    <div class="judge-card-title">{esc(f["title"])}</div>
    <div class="judge-card-text">{md_bold(f.get("body", ""))}</div>{loupe_html}
  </div>""")
    body = f"""
  {_card_headline(cfg)}
  <div class="findings-list-tight">{''.join(rows)}</div>"""
    return _card_shell(page_num, total, cfg.get("page_label", "发现透视"), body, ed.get("case_tag", "CASE"))


def _card_rewrites(report: Dict[str, Any], ed: Dict[str, Any], page_num: int, total: int) -> str:
    reds = _build_redactions(ed)
    cfg = ed["cards"]["rewrites_card"]
    max_diffs = int(cfg.get("max_diffs", 3))
    diffs = []
    for i, item in enumerate(ed["rewrites"][:max_diffs]):
        rw = next((r for r in report["rewrites"] if r["rewrite_id"] == item["rewrite_id"]), None)
        if rw is None:
            continue
        before = item.get("before_text") or rw.get("original_quote", "")
        after = item.get("after_text") or rw.get("rewritten_text", "")
        before, after = _redact(before, reds), _redact(after, reds)
        for s in item.get("strikes", []):
            before = before.replace(s, f'<span class="strike-text">{esc(s)}</span>', 1)
        for h in item.get("highlights", []):
            after = after.replace(h, f'<span class="green-badge">{esc(h)}</span>', 1)
        tag_cls = {"red": "alert", "green": "good", "neutral": ""}.get(item.get("badge_tone", ""), "")
        diffs.append(f"""
  <div class="diff-card">
    <div class="diff-card-header"><span class="diff-card-title">改写 {i + 1:02d} · {esc(item.get("label", ""))}（对齐 JD「{esc(item.get("jd_anchor", ""))}」）</span>
    <span class="diff-card-tag {tag_cls}">{esc(item.get("badge", ""))}</span></div>
    <div class="diff-card-body">
      <div class="diff-box before"><div class="diff-box-label">改前原句</div>{before}</div>
      <div class="diff-box after"><div class="diff-box-label">{esc(item.get("after_label", "改后定稿"))}</div>{after}</div>
    </div>
    <div class="diff-annotation"><span class="diff-annotation-stamp">红笔批注</span>
    <div class="diff-annotation-text">{md_bold(item.get("annotation", ""))}</div></div>
  </div>""")
    principles = "".join(f'<div class="principle-item">{esc(p)}</div>' for p in PRINCIPLES_ITEMS)
    body = f"""
  {_card_headline(cfg)}
  <div class="diff-list">{''.join(diffs)}</div>
  <div class="principles-box"><div class="principles-title"><span>● 事实保真红线（违反即重写）</span></div>
  <div class="principles-grid">{principles}</div></div>"""
    return _card_shell(page_num, total, cfg.get("page_label", "改写对照"), body, ed.get("case_tag", "CASE"))


def _card_actions(report: Dict[str, Any], ed: Dict[str, Any], page_num: int, total: int) -> str:
    cfg = ed["cards"]["actions_card"]
    rows = []
    for i, a in enumerate(ed["actions"]):
        template = ""
        if a.get("template"):
            green = ' green' if a.get("template_tone") == "green" else ""
            template = (f'<div class="template-box{green}"><div class="template-label">{esc(a.get("template_label", "话术模板"))}</div>'
                        f'<div class="template-content">{esc(a["template"])}</div></div>')
        chips = ""
        if a.get("chips"):
            chips = '<div class="check-chips-card">' + "".join(
                f'<span class="chip-card {"highlight" if c.get("highlight") else ""}">{esc(c["text"])}</span>'
                for c in a["chips"]) + '</div>'
        rows.append(f"""
  <div class="action-card">
    <div class="action-card-header"><span class="action-step-num {"primary" if a.get("badge_tone") == "red" else ""}">{esc(a.get("badge", f"第 {i + 1} 步"))}</span>
    <span class="action-timing-tag">{esc(a.get("timing_tag", ""))}</span></div>
    <div class="action-card-title">{esc(a["title"])}</div>
    <div class="action-card-desc">{md_bold(a.get("body", ""))}</div>{template}{chips}
  </div>""")
    takeaway = f"""
  <div class="bottom-takeaway-banner"><div class="takeaway-icon">💡</div>
  <div class="takeaway-text">{md_bold(cfg.get("takeaway", "改句子不会让匹配分上涨，分数只认写进简历的事实。"))}</div></div>"""
    b = _brand()
    brand_box = f"""
  <div class="card-brand-action-row" style="margin-top:14px;padding:12px 20px;background:#FFF;border:1.5px solid #E5E1D5;border-radius:10px;display:flex;justify-content:space-between;align-items:center;">
    <div style="display:flex;align-items:center;gap:12px;">
      <span style="background:#18181B;color:#FFF;padding:6px 16px;border-radius:20px;font-size:14px;font-weight:800;">🔍 {esc(b["search_entry"])}</span>
      <span style="font-size:14px;color:#52525B;font-weight:700;">{esc(b["cta"])}</span>
    </div>
    <span style="font-size:12px;color:#71717A;font-weight:600;">{esc(b.get("card_brand_sub", ""))}</span>
  </div>"""
    body = f"""
  {_card_headline(cfg)}
  <div class="actions-list">{''.join(rows)}</div>{takeaway}{brand_box}"""
    return _card_shell(page_num, total, cfg.get("page_label", "行动路线"), body, ed.get("case_tag", "CASE"))


def _card_evidence(report: Dict[str, Any], ed: Dict[str, Any], page_num: int, total: int) -> str:
    cfg = ed["cards"]["evidence_card"]
    reqs = {r["req_id"]: r for r in report["requirements"]}
    jobs_by_id = {j["job_id"]: j for j in report["jobs"]}
    cards = []
    for n in ed.get("evidence_notes", []):
        if not n.get("focus"):
            continue
        r = reqs.get(n["req_id"])
        if r is None:
            continue
        label, tone = REQ_STATUS_HUMAN[r["status"]]
        cards.append(f"""
  <div class="judge-card">
    <div class="judge-card-header"><span class="judge-card-title">{esc(r["text"])}</span>
    <span class="status-pill {tone}">{esc(label)}</span></div>
    <div class="judge-card-text">{md_bold(n.get("note", ""))}</div>
  </div>""")
    gates_html = ""
    for job in report["jobs"]:
        for g in job.get("gates", []):
            if g["status"] == "met":
                continue
            note = next((gn["note"] for gn in ed.get("gate_notes", []) if gn["gate_id"] == g["gate_id"]), "")
            label, tone = GATE_STATUS_HUMAN[g["status"]]
            job_badge = "" if job["job_id"] == report["primary_job_id"] else f'（{esc(job["title"])}）'
            gates_html += f"""
  <div class="judge-card">
    <div class="judge-card-header"><span class="judge-card-title">硬性门槛{job_badge}：{esc(g["text"])}</span>
    <span class="status-pill {tone}">{esc(label)}</span></div>
    <div class="judge-card-text">{md_bold(note)}</div>
  </div>"""
    body = f"""
  {_card_headline(cfg)}
  <div class="actions-list">{''.join(cards)}{gates_html}</div>"""
    return _card_shell(page_num, total, cfg.get("page_label", "判定与门槛"), body, ed.get("case_tag", "CASE"))


# ---------------------------------------------------------------------------
# 成员版分享卡（默认交付 1 张；内容组来自 editorial.member_card，样式为 T1 已验收定稿）
# ---------------------------------------------------------------------------

MEMBER_CSS = """
.member-card-page{display:flex;flex-direction:column;justify-content:space-between;height:100%;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Noto Sans CJK SC','Microsoft YaHei',sans-serif}
.member-header-bar{display:flex;justify-content:space-between;align-items:center;border-bottom:2.5px solid #18181B;padding-bottom:18px}
.member-header-brand{font-size:20px;font-weight:900;letter-spacing:.06em;color:#18181B;display:flex;align-items:center;gap:12px}
.member-header-badge{background:#DC2626;color:#FFF;font-size:15px;font-weight:800;padding:4px 12px;border-radius:6px}
.member-header-note{font-size:18px;font-weight:800;color:#52525B}
.member-decision-left{flex:1}
.member-decision{background:#FFF;border:2px solid #E5E1D5;border-radius:20px;padding:32px 40px;display:flex;align-items:center;justify-content:space-between;gap:32px;box-shadow:0 4px 20px rgba(0,0,0,0.03)}
.member-target-tag{display:inline-block;background:#F4F4F5;color:#52525B;font-size:18px;font-weight:800;padding:6px 16px;border-radius:8px;margin-bottom:14px}
.member-target-title{font-size:44px;font-weight:900;color:#18181B;line-height:1.2;margin-bottom:14px}
.member-verdict{display:inline-flex;align-items:center;gap:12px;padding:8px 20px;border-radius:10px;font-size:20px;font-weight:900}
.member-verdict.green{background:#F0FDF4;border:2px solid #86EFAC;color:#0F766E}
.member-verdict.amber{background:#FEF3C7;border:2px solid #FDE68A;color:#B45309}
.member-verdict.red{background:#FEF2F2;border:2px solid #FCA5A5;color:#B91C1C}
.member-verdict-note{font-size:16px;font-weight:700}
.member-score-box{text-align:center;background:#FAFAFA;border:2.5px dashed #D4CEBE;border-radius:20px;padding:20px 32px;min-width:200px}
.member-score-num{font-size:88px;font-weight:900;line-height:1;color:#DC2626;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
.member-score-label{font-size:17px;font-weight:800;color:#52525B;margin-top:8px}
.member-section-title{font-size:26px;font-weight:900;color:#18181B;display:flex;align-items:center;gap:12px;margin-bottom:16px}
.member-section-title::before{content:'';display:inline-block;width:6px;height:24px;background:#DC2626;border-radius:3px}
.member-findings{display:flex;flex-direction:column;gap:16px}
.member-finding{background:#FFF;border:2px solid #E5E1D5;border-radius:16px;padding:22px 28px;display:flex;gap:20px;align-items:flex-start}
.member-finding-badge{font-size:18px;font-weight:900;padding:6px 14px;border-radius:8px;white-space:nowrap;margin-top:2px;background:#F4F4F5;color:#18181B}
.member-finding-badge.advantage{background:#F0FDF4;color:#0F766E;border:1.5px solid #86EFAC}
.member-finding-badge.focus{background:#FEF2F2;color:#DC2626;border:1.5px solid #FCA5A5}
.member-finding-text{font-size:24px;line-height:1.55;color:#27272A;font-weight:600}
.member-finding-text strong{color:#18181B;font-weight:900}
.member-action{background:#FFFDF0;border:2.5px solid #EAB308;border-radius:18px;padding:24px 30px}
.member-action-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.member-action-tag{font-size:22px;font-weight:900;color:#854D0E}
.member-action-step{font-size:16px;font-weight:900;color:#A16207;background:#FEF08A;padding:5px 12px;border-radius:6px}
.member-action-content{font-size:22px;line-height:1.6;color:#451A03;font-weight:600}
.member-action-content strong{font-weight:900;color:#000}
.member-footer{border-top:2px dashed #D4CEBE;padding-top:24px;display:flex;justify-content:space-between;align-items:center}
.member-brand{display:flex;align-items:center;gap:18px}
.member-search-badge{display:flex;align-items:center;gap:10px;background:#18181B;color:#FFF;padding:12px 26px;border-radius:36px;font-size:20px;font-weight:900;box-shadow:0 4px 12px rgba(0,0,0,0.12)}
.member-brand-subtext{font-size:20px;color:#52525B;font-weight:800}
.member-footer-note{font-size:18px;color:#71717A;text-align:right;line-height:1.5;font-weight:600}
"""

# 成员卡画布基座（独立 HTML 文档用；预览页复用 .card-canvas 时不需要 body 规则）
MEMBER_CANVAS_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#27272A;display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Noto Sans CJK SC','Microsoft YaHei',sans-serif}
.card-canvas{width:1080px;height:1440px;background:#FBF9F5;position:relative;overflow:hidden;padding:56px 64px;display:flex;flex-direction:column;justify-content:space-between}
"""


def _member_gate_note(report: Dict[str, Any]) -> Tuple[str, str]:
    """硬门槛口径只从报告读：全过/待确认/未过三态，给出成员卡横幅注记与色调。"""
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    gates = job.get("gates", [])
    unmet = sum(1 for g in gates if g["status"] == "unmet")
    pending = sum(1 for g in gates if g["status"] == "pending_confirmation")
    if unmet:
        return f"有 {unmet} 项硬门槛未满足，先暂缓更稳妥", "red"
    if pending:
        return f"{pending} 项硬门槛待核实，投前先确认", "amber"
    return "硬门槛全部通过", "green"


def _card_member(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    """成员版分享卡：默认 1 张，1080×1440。分数/建议/门槛注记只从报告读，
    文案来自 member_card 内容组，品牌来自 brand.json——低分也不羞辱用户或夸大优势。"""
    mc = ed["member_card"]
    sp = report.get("share_payload", {})
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    score = sp.get("score", job.get("score"))
    score_label = sp.get("score_label", "简历证据匹配度")
    job_title = sp.get("job_title", job.get("title", ""))
    cat = JOB_CATEGORY_HUMAN.get(sp.get("job_category") or job.get("category", ""), "岗位方向未核实")
    suggestion = SUGGESTION_HUMAN[job["suggestion"]]
    if mc.get("verdict_note"):
        verdict_note, v_tone = mc["verdict_note"], {"prioritize": "green", "revise_then_apply": "amber", "hold": "red"}[job["suggestion"]]
    else:
        verdict_note, v_tone = _member_gate_note(report)
    kicker = mc.get("kicker", f"目标岗位评估 · {cat}")
    tone_cls = {"prioritize": "green", "revise_then_apply": "amber", "hold": "red"}[job["suggestion"]]
    b = _brand()
    findings_html = "".join(f"""
    <div class="member-finding">
      <div class="member-finding-badge {esc(f.get('tone', ''))}">{esc(f.get('badge', ''))}</div>
      <div class="member-finding-text"><strong>{esc(f.get('lead', ''))}</strong>{esc(f.get('text', ''))}</div>
    </div>""" for f in mc.get("findings", []))
    act = mc.get("action", {})
    footer_note = "<br>".join(esc(n) for n in b.get("member_footer_note", []))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>求职体检卡 · {esc(job_title)}</title>
<style>{MEMBER_CANVAS_CSS}{MEMBER_CSS}</style>
</head>
<body>

<div class="card-canvas">
  <div class="member-card-page">
  <div class="member-header-bar">
    <div class="member-header-brand">
      {esc(b.get("member_header", "求职匹配体检单"))} <span class="member-header-badge">{esc(b.get("member_badge", "个人诊断报告"))}</span>
    </div>
    <div class="member-header-note">{esc(b.get("member_header_note", ""))}</div>
  </div>

  <div class="member-decision">
    <div class="member-decision-left">
      <div class="member-target-tag">{esc(kicker)}</div>
      <div class="member-target-title">{esc(job_title)}</div>
      <div class="member-verdict {tone_cls}">
        <span>建议：{esc(suggestion)}</span>
        <span class="member-verdict-note">({esc(verdict_note)})</span>
      </div>
    </div>
    <div class="member-score-box">
      <div class="member-score-num">{esc(score)}</div>
      <div class="member-score-label">{esc(score_label)}</div>
    </div>
  </div>

  <div>
    <div class="member-section-title">核心诊断发现与证明事实</div>
    <div class="member-findings">{findings_html}
    </div>
  </div>

  <div class="member-action">
    <div class="member-action-header">
      <span class="member-action-tag">📌 {esc(act.get("tag", "下一步建议"))}</span>
      <span class="member-action-step">{esc(act.get("step_label", "现在就能做"))}</span>
    </div>
    <div class="member-action-content"><strong>{esc(act.get("lead", ""))}</strong>{esc(act.get("text", ""))}</div>
  </div>

  <div class="member-footer">
    <div class="member-brand">
      <div class="member-search-badge">🔍 {esc(b["search_entry"])}</div>
      <span class="member-brand-subtext">{esc(b["cta"])}</span>
    </div>
    <div class="member-footer-note">{footer_note}</div>
  </div>
  </div>
</div>

</body>
</html>"""


CARD_ORDER = [("cover", "card-cover.html", _card_cover),
              ("findings_card", "card-findings.html", _card_findings),
              ("rewrites_card", "card-rewrites.html", _card_rewrites),
              ("actions_card", "card-actions.html", _card_actions),
              ("evidence_card", "card-evidence.html", _card_evidence)]

CARD_DESC = {"cover": "痛点透视与结论", "findings_card": "逐条发现与原文检视",
             "rewrites_card": "改前改后对照", "actions_card": "三步行动与话术清单",
             "evidence_card": "重点判定与一票条件"}


def render_cards(report: Dict[str, Any], ed: Dict[str, Any]) -> List[Tuple[str, str]]:
    """返回 [(filename, html), …]，文件名按卡片顺序编号。"""
    cfg = ed.get("cards", {})
    enabled = [(key, fn, fn_) for key, fn, fn_ in CARD_ORDER if cfg.get(key)]
    total = len(enabled)
    out = []
    for idx, (key, filename, renderer) in enumerate(enabled, start=1):
        stem = filename.replace(".html", "")
        numbered = f"card-{idx:02d}-{stem.split('-', 1)[1]}.html"
        out.append((numbered, renderer(report, ed, idx, total)))
    return out


def render_cards_preview(report: Dict[str, Any], ed: Dict[str, Any], cards: List[Tuple[str, str]]) -> str:
    """预览页把卡片 DOM 内联（同源同 DOM）：显示与 PNG 导出共用一份排版实现。"""
    cfg = ed.get("cards", {})
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    tiles = []
    card_bodies = []
    for idx, (filename, card_html) in enumerate(cards, start=1):
        key = next((k for k, fn, _ in CARD_ORDER if fn.replace(".html", "") in filename), "cover")
        label = cfg.get(key, {}).get("page_label", "卡片")
        body = card_html.split('<div class="card-canvas">', 1)[1].rsplit("</div>\n</body>", 1)[0]
        # 预览缩放：卡片原始 1080×1440，等比缩进画格
        tiles.append(f"""
  <div class="card-preview-wrap">
    <div class="card-meta-bar"><span class="card-meta-title">{idx:02d} · {esc(label)}</span>
    <span class="card-meta-dim">1080 × 1440</span></div>
    <div class="scaled-frame-container" data-card-idx="{idx}"><div class="card-canvas scaled" data-export="card-{idx:02d}">{body}</div></div>
    <div class="card-download-row"><span style="font-size:13px;color:#A1A1AA;">{esc(CARD_DESC.get(key, ""))}</span>
    <button class="btn" data-export-one="{idx:02d}">下载 PNG</button></div>
  </div>""")
    total = len(cards)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>编辑批注风发布卡片 · {esc(job["title"])}（1080×1440 · {total} 张）</title>
<style>
body{{background:#1E1E24;color:#E4E4E7;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,sans-serif;
padding:32px 20px;min-height:100vh}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
.preview-header{{max-width:1280px;margin:0 auto 32px;display:flex;justify-content:space-between;align-items:center;
flex-wrap:wrap;gap:16px;border-bottom:1px solid #3F3F46;padding-bottom:20px}}
.preview-title h1{{font-size:24px;font-weight:800;color:#FFF;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.preview-title p{{font-size:14px;color:#A1A1AA;margin-top:6px}}
.preview-nav{{display:flex;gap:10px}}
.btn{{padding:8px 16px;border-radius:6px;font-size:13px;font-weight:700;background:#27272A;color:#FFF;
border:1px solid #3F3F46;cursor:pointer;text-decoration:none}}
.btn:hover{{background:#3F3F46}}
.btn-primary{{background:#DC2626;border-color:#EF4444}}
.btn-primary:hover{{background:#B91C1C}}
.gallery-container{{max-width:1280px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
gap:32px;align-items:start}}
.card-preview-wrap{{background:#27272A;border:1px solid #3F3F46;border-radius:12px;overflow:hidden;
display:flex;flex-direction:column}}
.card-meta-bar{{padding:12px 18px;display:flex;justify-content:space-between;align-items:center;background:#18181B;
border-bottom:1px solid #3F3F46}}
.card-meta-title{{font-size:14px;font-weight:800;color:#FFF}}
.card-meta-dim{{font-size:12px;color:#A1A1AA;background:#27272A;padding:2px 8px;border-radius:4px}}
.scaled-frame-container{{width:100%;aspect-ratio:3/4;position:relative;background:#FBF9F5;overflow:hidden}}
.card-canvas.scaled{{transform-origin:top left}}
.card-download-row{{padding:12px 18px;background:#18181B;border-top:1px solid #3F3F46;display:flex;
justify-content:space-between;align-items:center;gap:8px}}
</style>
<style id="cardCss">{CARD_CSS}</style>
</head>
<body>
<div class="preview-header">
  <div class="preview-title">
    <h1><span>发布卡片 · 编辑批注风</span><span style="font-size:12px;background:#DC2626;color:#FFF;padding:2px 8px;border-radius:4px;">1080×1440 PNG · {total} 张</span></h1>
    <p>纸白底 · 黑大标 · 红批注 · 局部放大 · 改前改后对照 —— 预览与导出共用同一排版，无样式漂移</p>
  </div>
  <div class="preview-nav"><button class="btn btn-primary" id="btnExportAll">导出全部 PNG</button></div>
</div>
<div class="gallery-container">{''.join(tiles)}</div>
<script>
(function(){{
  function scaleCards(){{
    document.querySelectorAll('.scaled-frame-container').forEach(function(box){{
      var card = box.querySelector('.card-canvas');
      card.style.transform = 'scale(' + (box.offsetWidth / 1080) + ')';
    }});
  }}
  window.addEventListener('resize', scaleCards);
  window.addEventListener('load', scaleFramesSoft);
  function scaleFramesSoft(){{ scaleCards(); }}
  setTimeout(scaleCards, 60);

  function exportCard(idx, done){{
    var card = document.querySelector('[data-export="card-' + idx + '"]');
    var clone = card.cloneNode(true);
    clone.style.transform = 'none';
    clone.classList.remove('scaled');
    var css = document.getElementById('cardCss').outerHTML;
    var wrap = document.createElement('div');
    wrap.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
    wrap.appendChild(document.createElement('div'));
    wrap.firstChild.innerHTML = css;
    wrap.firstChild.appendChild(clone);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440">' +
      '<foreignObject width="100%" height="100%">' + new XMLSerializer().serializeToString(wrap) + '</foreignObject></svg>';
    var blob = new Blob([svg], {{type: 'image/svg+xml;charset=utf-8'}});
    var url = URL.createObjectURL(blob);
    var img = new Image();
    img.onload = function(){{
      var canvas = document.createElement('canvas');
      canvas.width = 1080; canvas.height = 1440;
      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#FBF9F5';
      ctx.fillRect(0, 0, 1080, 1440);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob(function(pngBlob){{
        var link = document.createElement('a');
        link.download = 'card-' + idx + '.png';
        link.href = URL.createObjectURL(pngBlob);
        link.click();
        setTimeout(function(){{ URL.revokeObjectURL(link.href); }}, 4000);
        done(true);
      }}, 'image/png');
    }};
    img.onerror = function(){{ done(false); }};
    img.src = url;
  }}
  document.getElementById('btnExportAll').addEventListener('click', function(){{
    var btn = this; btn.disabled = true; var old = btn.textContent;
    var total = {total};
    var queue = [];
    for (var i = 1; i <= total; i++) queue.push(i);
    (function next(){{
      if (!queue.length) {{ btn.textContent = old; btn.disabled = false; return; }}
      var i = queue.shift();
      btn.textContent = '导出中 ' + i + '/' + total + '…';
      exportCard(i, function(){{ setTimeout(next, 350); }});
    }})();
  }});
  document.querySelectorAll('[data-export-one]').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      var idx = btn.getAttribute('data-export-one');
      var old = btn.textContent; btn.textContent = '导出中…'; btn.disabled = true;
      exportCard(idx, function(){{ btn.textContent = old; btn.disabled = false; }});
    }});
  }});
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 小红书发布 Markdown
# ---------------------------------------------------------------------------

def _basis_label(basis: Dict[str, Any]) -> str:
    parts = []
    if basis.get("finding") is not None:
        parts.append(f"发现 {basis['finding']}")
    if basis.get("rewrite") is not None:
        parts.append(f"改写 {basis['rewrite']}")
    if basis.get("gate") is not None:
        parts.append("门槛待确认")
    if basis.get("action") is not None:
        parts.append(f"行动 {basis['action']}")
    return " / ".join(parts)


def render_social_md(report: Dict[str, Any], ed: Dict[str, Any]) -> str:
    social = ed["social"]
    job = next(j for j in report["jobs"] if j["job_id"] == report["primary_job_id"])
    titles = "\n".join(
        f"{i}. **{t['text']}**（依据：{_basis_label(t.get('basis', {}))}）"
        for i, t in enumerate(social["titles"], start=1))
    note = social.get("synthetic_note",
                      "（分数 = 简历证据对 JD 的覆盖度，不代表能力或录取概率；案例已匿名，素材为合成案例。）")
    # 正文已自带免责尾注时不重复追加（编排作者可能把尾注写进 body_md）
    if note and note.strip() in social["body_md"]:
        note = ""
    # 尾注定稿口径（MYW-69 终验收口）：note 非空 → 空行分隔 + 末尾换行
    # （与用户定稿小样 docs/mockup/social-post.md 的排版一致）；去重命中（note 空）→ 仅正文末换行。
    tail = f"\n\n{note}\n" if note else "\n"
    return f"""# 小红书发布素材（{esc(job["title"])} · {esc(ed.get("case_tag", report["case_id"]))}）

> 文案遵循求职内容规范表达标准；每条标题均有报告证据对应。发布前请人工预览，不自动发布。

## 备选标题（三选一）

{titles}

## 发布正文

{social["body_md"]}{tail}"""


# ---------------------------------------------------------------------------
# 生成入口
# ---------------------------------------------------------------------------

def generate_bundle(report: Dict[str, Any], ed: Dict[str, Any], outdir: Path, brand_path: Optional[Path] = None) -> Dict[str, Any]:
    """校验 + 渲染全套交付资产到 outdir；返回生成清单。校验失败抛 ValueError，不产出半成品、不回退旧模板。"""
    global _BRAND
    errors = validate_editorial(report, ed)
    if errors:
        raise ValueError("内容编排契约校验失败（" + str(len(errors)) + " 项）：\n  - " + "\n  - ".join(errors))
    _BRAND = load_brand(brand_path)

    cards_dir = outdir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    cards = render_cards(report, ed)

    report_path = outdir / "report.html"
    report_html = render_editorial_report(report, ed)
    _assert_redacted(report_html, report.get("private_markers", []), _build_redactions(ed))
    report_path.write_text(report_html, encoding="utf-8")
    preview_path = outdir / "cards-preview.html"
    preview_path.write_text(render_cards_preview(report, ed, cards), encoding="utf-8")
    social_path = outdir / "social-post.md"
    social_path.write_text(render_social_md(report, ed), encoding="utf-8")
    card_paths = []
    for filename, card_html in cards:
        p = cards_dir / filename
        p.write_text(card_html, encoding="utf-8")
        card_paths.append(p)
    manifest = {"report": report_path, "preview": preview_path, "social": social_path, "cards": card_paths}
    manifest["member_card"] = None
    if ed.get("editorial_version") == EDITORIAL_VERSION:
        member_path = outdir / "member-card-01.html"
        member_path.write_text(_card_member(report, ed), encoding="utf-8")
        manifest["member_card"] = member_path
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="默认交付链路：编辑批注风报告 + 成员版分享卡 + 案例卡 + 预览 + 发布 MD")
    ap.add_argument("--input", "-i", required=True, help="评分报告 JSON（jd-match-report/0.1.0）")
    ap.add_argument("--editorial", "-e", required=True, help="内容编排 JSON（jd-match-editorial/0.2.0）")
    ap.add_argument("--outdir", "-o", required=True, help="输出目录（report.html / member-card-01.html / cards/ / cards-preview.html / social-post.md）")
    ap.add_argument("--brand", default=None, help="品牌配置 JSON（缺省用 references/brand.json；品牌独立于候选人材料）")
    args = ap.parse_args()

    input_path, ed_path, outdir = Path(args.input), Path(args.editorial), Path(args.outdir)
    for p, label in ((input_path, "输入"), (ed_path, "内容编排")):
        if not p.exists():
            print(f"[错误] {label}文件不存在: {p}", file=sys.stderr)
            return 1
    try:
        report = json.loads(input_path.read_text(encoding="utf-8"))
        ed = json.loads(ed_path.read_text(encoding="utf-8"))
        manifest = generate_bundle(report, ed, outdir, Path(args.brand) if args.brand else None)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        print("[失败处理] 修复内容编排或品牌配置后重试；不得改用旧链路（render_report.py / build_share.py）充当完成交付。", file=sys.stderr)
        return 1

    print(f"[成功] 交付资产生成完毕 → {outdir}")
    print(f"  报告     {manifest['report'].name}（{manifest['report'].stat().st_size} 字节）")
    if manifest.get("member_card"):
        print(f"  成员卡   {manifest['member_card'].name}（成员版分享卡，默认 1 张）")
    print(f"  预览     {manifest['preview'].name}")
    print(f"  发布     {manifest['social'].name}")
    for p in manifest["cards"]:
        print(f"  案例卡   cards/{p.name}")
    print("  PNG      用 scripts/export_png.py 逐张导出（成员卡与案例卡均 1080×1440），或预览页「导出全部 PNG」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
