#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_score.py — T1 校准用确定性复算器与契约检查器。

定位（重要）：
  * 本脚本是 T1 的「可复算产物」：证明 references/scoring-rubric.md 0.1.0 的算法
    可以不依赖任何模型、纯凭结构化数据复现黄金案例中的每一个分数。
  * 它不是 T2 的正式评分脚本（score_report.py 由 T2 交付）；T2 应复用本文件的
    算法口径（WEIGHTS/COEFS/round_half_up/决策表），不得另立标准。

用法：
  python3 scripts/reference_score.py --check examples/case-a-freshgrad-ops/expected.json
  python3 scripts/reference_score.py --show  examples/case-a-freshgrad-ops/expected.json

退出码：0 = 契约与复算全部通过；1 = 存在错误（打印全部错误）。
仅依赖 Python 标准库。
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "jd-match-report/0.1.0"
RUBRIC_VERSION = "jd-match-rubric/0.1.0"

# ---- rubric 0.1.0 常量（唯一算分口径；与 scoring-rubric.md §2/§3 一致）----
WEIGHTS = {"must": 3, "normal": 2, "bonus": 1}
COEFS = {"supported": 1.0, "partial": 0.5, "unclear": 0.0, "unmet": 0.0, "unknown": 0.0}
STATUSES = ("supported", "partial", "unclear", "unmet", "unknown")
IMPORTANCE = ("must", "normal", "bonus")
IMPORTANCE_SOURCES = ("jd_explicit", "system_default")
GATE_STATUSES = ("met", "unmet", "pending_confirmation")
SUGGESTIONS = ("prioritize", "revise_then_apply", "hold")
CATEGORIES = ("skill", "tool", "experience", "domain", "education", "soft", "other")
REQ_CATEGORIES = ("product", "operations", "marketing", "data", "engineering", "design", "category_unverified")
FACT_OR_SKILL = ("fact", "skill")

TOP_REQUIRED = [
    "schema_version", "rubric_version", "case_id", "synthetic", "private_markers",
    "sources", "candidate_stage", "parse_warnings", "jobs", "requirements",
    "evidence", "answers", "primary_job_id", "primary_selection_reason",
    "rewrites", "actions", "share_payload",
]
SHARE_ALLOWED_KEYS = {
    "standalone", "anonymized", "score", "score_label", "job_title", "job_category",
    "headline_findings", "gate_notes", "disclaimer",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
FORBIDDEN_KEY_TOKENS = ("confidence", "置信", "probability", "ats_score")


# ---- 算分核心 ----

def round_half_up(x: float) -> int:
    """四舍五入（半分位向上）。不用内建 round()（银行家舍入）。"""
    return int(math.floor(x + 0.5))


def counted_requirements(reqs):
    return [r for r in reqs if not r.get("merged_into")]


def score_of(job_id: str, reqs):
    """score = floor(100 × Σ(w×coef)/Σ(w) + 0.5)；无可计要求返回 None。"""
    counted = [r for r in reqs if r["job_id"] == job_id]
    counted = counted_requirements(counted)
    total_w = sum(WEIGHTS[r["importance"]] for r in counted)
    if not counted or total_w == 0:
        return None
    contrib = sum(WEIGHTS[r["importance"]] * COEFS[r["status"]] for r in counted)
    return round_half_up(100.0 * contrib / total_w)


def unknown_count_of(job_id: str, reqs) -> int:
    counted = counted_requirements([r for r in reqs if r["job_id"] == job_id])
    return sum(1 for r in counted if r["status"] in ("unclear", "unknown"))


def derive_suggestion(job: dict, reqs) -> str:
    """scoring-rubric.md §5 决策表，按序命中即停。"""
    gates = job.get("gates", [])
    if any(g["status"] == "unmet" for g in gates):
        return "hold"
    if any(g["status"] == "pending_confirmation" for g in gates):
        return "revise_then_apply"
    counted = counted_requirements([r for r in reqs if r["job_id"] == job["job_id"]])
    unknown = sum(1 for r in counted if r["status"] in ("unclear", "unknown"))
    score = job.get("score")
    if score is not None and score >= 70 and counted and unknown * 3 <= len(counted):
        return "prioritize"
    return "revise_then_apply"


def apply_variant(data: dict, variant: dict) -> dict:
    """把补充回答带来的状态变更应用到数据副本（不修改原数据——旧报告保留）。"""
    changed = {c["req_id"]: c for c in variant["changes"]}
    out = json.loads(json.dumps(data, ensure_ascii=False))
    for r in out["requirements"]:
        if r["req_id"] in changed:
            r["status"] = changed[r["req_id"]]["status"]
    return out


# ---- 契约检查（返回错误字符串列表）----

def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def check_contract(data: dict):
    errors = []

    def err(msg):
        errors.append(msg)

    # 1. 版本与必备字段
    for key in TOP_REQUIRED:
        if key not in data:
            err(f"缺少必备字段 {key}")
    if errors:
        return errors
    if data["schema_version"] != SCHEMA_VERSION:
        err(f"schema_version 应为 {SCHEMA_VERSION}，实际 {data['schema_version']}")
    if data["rubric_version"] != RUBRIC_VERSION:
        err(f"rubric_version 应为 {RUBRIC_VERSION}，实际 {data['rubric_version']}")
    # synthetic 契约（0.1.0 修订 2026-09-11，MYW-58 报备）：布尔，true=合成/false=真实材料。
    # 「黄金案例必须为 true」是本仓库红线，归 tests/test_golden_cases.py 管辖，不再是通用契约约束。
    if not isinstance(data["synthetic"], bool):
        err(f"synthetic 必须为布尔值（true=合成材料 / false=真实材料），实际 {data['synthetic']!r}")
    if not data["private_markers"]:
        err("private_markers 不能为空")
    for marker in data["private_markers"]:
        if not isinstance(marker, str) or len(marker) < 2:
            err(f"private_markers 每项至少 2 个字符（单字符标记会造成大面积误报），实际 {marker!r}")

    # 2. 枚举与 ID 形态
    for s in data["sources"]:
        if not re.match(r"^src-[a-z0-9-]+$", s["source_id"]):
            err(f"source_id 形态非法: {s['source_id']}")
        if s["kind"] not in ("resume", "jd"):
            err(f"source kind 非法: {s['kind']}")
    if data["candidate_stage"] not in ("fresh_grad", "early_career", "experienced", "unspecified"):
        err(f"candidate_stage 非法: {data['candidate_stage']}")

    job_ids = {j["job_id"] for j in data["jobs"]}
    src_ids = {s["source_id"] for s in data["sources"]}
    ev_ids = {e["evidence_id"] for e in data["evidence"]}
    ans_ids = {a["answer_id"] for a in data["answers"]}
    req_ids = {r["req_id"] for r in data["requirements"]}

    # 3. 要求逐条检查
    for r in data["requirements"]:
        rid = r["req_id"]
        if r["importance"] not in IMPORTANCE:
            err(f"{rid}: importance 非法 {r['importance']}")
        if r["importance_source"] not in IMPORTANCE_SOURCES:
            err(f"{rid}: importance_source 非法")
        if r["status"] not in STATUSES:
            err(f"{rid}: status 非法 {r['status']}")
        if r["category"] not in CATEGORIES:
            err(f"{rid}: category 非法 {r['category']}")
        if r["weight"] != WEIGHTS[r["importance"]]:
            err(f"{rid}: weight {r['weight']} 与 rubric 权重 {WEIGHTS[r['importance']]} 不一致")
        if r["job_id"] not in job_ids:
            err(f"{rid}: job_id 无法解析 {r['job_id']}")
        for ev in r["evidence_ids"]:
            if ev not in ev_ids:
                err(f"{rid}: evidence_id 无法解析 {ev}")
        for an in r["answer_ids"]:
            if an not in ans_ids:
                err(f"{rid}: answer_id 无法解析 {an}")
        if r["status"] in ("supported", "partial") and not (r["evidence_ids"] or r["answer_ids"]):
            err(f"{rid}: supported/partial 必须引用证据或补充回答")
        if r["status"] == "unknown" and r.get("merged_into"):
            err(f"{rid}: 被去重条目不应再有状态")
        if "merged_into" in r and r["merged_into"] not in req_ids:
            err(f"{rid}: merged_into 指向不存在的 req")

    # 4. 门槛：unmet/met 必须有证据。unmet 禁止从缺失信息推断不满足；
    #    met 按 rubric §4 定义为「有证据满足」，无引用不得断言满足（MYW-64 与 T2 对齐）。
    for job in data["jobs"]:
        for g in job["gates"]:
            if g["status"] not in GATE_STATUSES:
                err(f"{g['gate_id']}: gate status 非法")
            if g["status"] == "unmet" and not g.get("evidence_ids"):
                err(f"{g['gate_id']}: unmet 门槛必须引用证据，禁止从缺失信息推断不满足")
            if g["status"] == "met" and not g.get("evidence_ids"):
                err(f"{g['gate_id']}: met 门槛必须引用证据，禁止无引用的满足判断")
            for ev in g.get("evidence_ids", []):
                if ev not in ev_ids:
                    err(f"{g['gate_id']}: evidence_id 无法解析 {ev}")

    # 5. 分数复算（核心：从判定逆向可算出同一分数）
    for job in data["jobs"]:
        if job["jd_source_id"] not in src_ids:
            err(f"{job['job_id']}: jd_source_id 无法解析")
        if job["category"] not in REQ_CATEGORIES:
            err(f"{job['job_id']}: category 非法 {job['category']}")
        derived = score_of(job["job_id"], data["requirements"])
        if job["scoring_status"] == "ok":
            if derived is None:
                err(f"{job['job_id']}: scoring_status=ok 但无可计要求，应为 insufficient_input + score=null")
            elif job["score"] != derived:
                err(f"{job['job_id']}: 分数不可复算 recorded={job['score']} derived={derived}")
            if not isinstance(job["score"], int):
                err(f"{job['job_id']}: score 必须为整数（禁止小数伪精度）")
        if job["unknown_count"] != unknown_count_of(job["job_id"], data["requirements"]):
            err(f"{job['job_id']}: unknown_count 与计算不一致 recorded={job['unknown_count']} "
                f"derived={unknown_count_of(job['job_id'], data['requirements'])}")
        if job["suggestion"] not in SUGGESTIONS:
            err(f"{job['job_id']}: suggestion 非法")
        dsg = derive_suggestion(job, data["requirements"])
        if job["suggestion"] != dsg:
            err(f"{job['job_id']}: 建议与决策表不一致 recorded={job['suggestion']} derived={dsg}")
        if "各自 JD 的证据覆盖" not in job["rank_rationale"]:
            err(f"{job['job_id']}: rank_rationale 必须声明「各自 JD 的证据覆盖」口径")

    ranks = sorted(j["rank"] for j in data["jobs"])
    if ranks != list(range(1, len(data["jobs"]) + 1)):
        err(f"rank 必须为 1..n 的排列，实际 {ranks}")
    if data["primary_job_id"] not in job_ids:
        err("primary_job_id 无法解析")

    # 6. 改写：只属主目标；事实与待补字段齐备；无凑数
    for rw in data["rewrites"]:
        if rw["job_id"] != data["primary_job_id"]:
            err(f"{rw['rewrite_id']}: 重点改写只属于主目标岗位")
        if rw["pending_fill"]:
            if "rewritten_text" in rw:
                err(f"{rw['rewrite_id']}: 待补项不得产出可复制文本")
            if not rw.get("target_gap") or not rw.get("ask"):
                err(f"{rw['rewrite_id']}: 待补项需 target_gap 与 ask")
        else:
            if not rw.get("original_quote") or not rw.get("rewritten_text"):
                err(f"{rw['rewrite_id']}: 有效改写需 original_quote 与 rewritten_text")
        if "new_facts" not in rw:
            err(f"{rw['rewrite_id']}: 必须声明 new_facts（纯润色为空）")
        for ev in rw.get("numbers_from", []):
            if ev not in ev_ids:
                err(f"{rw['rewrite_id']}: numbers_from 无法解析 {ev}")
    effective = [rw for rw in data["rewrites"] if not rw["pending_fill"]]
    if len(effective) > 5:
        err(f"有效改写 {len(effective)} 处超过 5 处上限")

    # 7. 行动：恰好 3 项，全部属主目标
    if len(data["actions"]) != 3:
        err(f"主目标行动必须恰好 3 项，实际 {len(data['actions'])}")
    if [a["order"] for a in data["actions"]] != [1, 2, 3]:
        err("行动 order 必须为 1,2,3")
    for a in data["actions"]:
        if a["job_id"] != data["primary_job_id"]:
            err(f"{a['action_id']}: 行动只属主目标岗位")
        if a["fact_or_skill"] not in FACT_OR_SKILL:
            err(f"{a['action_id']}: fact_or_skill 非法")

    # 8. 补充回答变体：分数变化可复算且必须注明来源
    for var in data.get("answer_variants", []):
        for aid in var["answer_ids"]:
            if aid not in ans_ids:
                err(f"answer_variants: answer_id 无法解析 {aid}")
        mutated = apply_variant(data, var)
        for job in mutated["jobs"]:
            derived = score_of(job["job_id"], mutated["requirements"])
            if job["job_id"] in var["job_scores"]:
                if var["job_scores"][job["job_id"]] != derived:
                    err(f"answer_variants[{var['answer_ids']}]: {job['job_id']} 变体分数不可复算 "
                        f"recorded={var['job_scores'][job['job_id']]} derived={derived}")
            elif derived != job["score"]:
                err(f"answer_variants[{var['answer_ids']}]: {job['job_id']} 分数变化未记录")

    # 9. 分享载荷隐私（白名单 + 标记扫描）
    errors.extend(check_share_privacy(data))

    # 10. 禁止伪精度/未校准置信度
    def _walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(tok in k.lower() for tok in FORBIDDEN_KEY_TOKENS):
                    err(f"禁止字段 {path}.{k}（未校准的置信度/ATS 分）")
                if k in ("score",) and isinstance(v, float):
                    err(f"{path}.{k} 为小数：分数必须为整数")
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(data)

    # 11. 材料不足路径：无要求则不得出分
    if not data["requirements"]:
        for job in data["jobs"]:
            if job["score"] is not None or job["scoring_status"] != "insufficient_input":
                err(f"{job['job_id']}: 无可判定要求时不得出总分（不能伪装成 0 分）")

    return errors


def check_share_privacy(data: dict):
    """分享载荷隐私边界：键白名单 + private_markers/邮箱/电话扫描。"""
    errors = []
    sp = data["share_payload"]
    extra = set(sp.keys()) - SHARE_ALLOWED_KEYS
    if extra:
        errors.append(f"share_payload 含白名单外字段: {sorted(extra)}")
    for key in ("standalone", "anonymized"):
        if sp.get(key) is not True:
            errors.append(f"share_payload.{key} 必须为 true")
    if sp.get("score_label") != "简历证据匹配度":
        errors.append("share_payload.score_label 必须为「简历证据匹配度」（不得写成能力分/ATS 分）")
    primary = next((j for j in data["jobs"] if j["job_id"] == data["primary_job_id"]), None)
    if primary is not None and sp.get("score") != primary["score"]:
        errors.append(f"share_payload.score {sp.get('score')} 与主目标分数 {primary['score']} 不一致")
    strings = list(_iter_strings({k: v for k, v in sp.items()}))
    for s in strings:
        for marker in data["private_markers"]:
            if marker in s:
                errors.append(f"share_payload 泄漏 private_marker「{marker}」: {s[:40]}…")
        if EMAIL_RE.search(s):
            errors.append(f"share_payload 疑似含邮箱: {s[:40]}…")
        if PHONE_RE.search(s):
            errors.append(f"share_payload 疑似含手机号: {s[:40]}…")
    return errors


# ---- CLI ----

def derive_table(data: dict) -> str:
    lines = []
    for job in data["jobs"]:
        reqs = counted_requirements([r for r in data["requirements"] if r["job_id"] == job["job_id"]])
        lines.append(f"岗位 {job['job_id']}（{job['title']} / {job['category']}）")
        tw = tc = 0.0
        for r in reqs:
            w = WEIGHTS[r["importance"]]
            c = COEFS[r["status"]]
            tw += w
            tc += w * c
            lines.append(f"  {r['req_id']:<14} {r['importance']:<6} w={w} {r['status']:<9} coef={c} 贡献={w*c:g}")
        lines.append(f"  Σ权重={tw:g}  Σ贡献={tc:g}  分数=floor(100×{tc:g}/{tw:g}+0.5)={score_of(job['job_id'], data['requirements'])}"
                     f"  记录={job['score']}")
        for g in job["gates"]:
            lines.append(f"  门槛 {g['gate_id']}: {g['status']}")
        dsg = derive_suggestion(job, data["requirements"])
        lines.append(f"  建议 derived={dsg} recorded={job['suggestion']}  未知项={unknown_count_of(job['job_id'], data['requirements'])}")
        lines.append("")
    for var in data.get("answer_variants", []):
        mutated = apply_variant(data, var)
        for jid, recorded in var["job_scores"].items():
            derived = score_of(jid, mutated["requirements"])
            lines.append(f"变体 {var['answer_ids']} → {jid}: derived={derived} recorded={recorded}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="T1 评分契约复算器")
    ap.add_argument("--check", metavar="FILE", help="校验契约并复算分数")
    ap.add_argument("--show", metavar="FILE", help="打印逐项推导")
    args = ap.parse_args(argv)
    if not args.check and not args.show:
        ap.error("需要 --check 或 --show")

    path = Path(args.check or args.show)
    data = json.loads(path.read_text(encoding="utf-8"))

    if args.show:
        print(derive_table(data))
        return 0

    errors = check_contract(data)
    print(derive_table(data))
    if errors:
        print(f"\n契约检查失败（{len(errors)} 项）：")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("\n契约检查通过：分数可复算、引用可解析、建议符合决策表、分享载荷通过隐私扫描。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
