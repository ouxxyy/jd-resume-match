#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_report.py — T2 报告数据契约校验器（结构 + 引用 + 内容约束 + 隐私）。

定位（重要）：
  * 本脚本是 T2 的正式契约校验器：skill 分析产出的报告 JSON 必须先通过本校验，
    才允许进入评分与渲染。校验失败时修复数据，禁止输出假完整报告。
  * 唯一口径来源：references/report-contract.schema.json（结构层）与
    references/scoring-rubric.md 0.1.0（语义层）。语义检查与 T1 的
    scripts/reference_score.py 保持同判（同判性由 tests 固定），本文件不另立标准。
  * 结构层实现了 schema 实际用到的 draft-07 子集校验器（零依赖），直接消费
    schema 文件本身，避免手工转抄造成漂移。

用法：
  python3 scripts/validate_report.py --input examples/case-a-freshgrad-ops/expected.json
  python3 scripts/validate_report.py --input report.json --quiet

退出码：0 = 全部通过；1 = 存在错误（打印全部错误）；2 = 用法/IO 错误。
仅依赖 Python 标准库（Python 3.9+）。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "report-contract.schema.json"

SCHEMA_VERSION = "jd-match-report/0.1.0"
RUBRIC_VERSION = "jd-match-rubric/0.1.0"

# ---- rubric 0.1.0 常量（唯一算分口径；与 scoring-rubric.md §2/§3/§5 一致）----
WEIGHTS = {"must": 3, "normal": 2, "bonus": 1}
COEFS = {"supported": 1.0, "partial": 0.5, "unclear": 0.0, "unmet": 0.0, "unknown": 0.0}
STATUSES = ("supported", "partial", "unclear", "unmet", "unknown")
IMPORTANCE = ("must", "normal", "bonus")
GATE_STATUSES = ("met", "unmet", "pending_confirmation")
SUGGESTIONS = ("prioritize", "revise_then_apply", "hold")

SHARE_ALLOWED_KEYS = {
    "standalone", "anonymized", "score", "score_label", "job_title", "job_category",
    "headline_findings", "gate_notes", "disclaimer",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
FORBIDDEN_KEY_TOKENS = ("confidence", "置信", "probability", "ats_score")


# ================= JSON Schema draft-07 子集校验器 =================
# 仅实现 references/report-contract.schema.json 用到的关键字：
# type / const / enum / required / properties / additionalProperties(false) /
# items / pattern / minLength / minItems / maxItems / minimum / maximum / description(忽略)

def _type_ok(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":  # JSON Schema 语义：true/false 不是整数
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "null":
        return value is None
    return True


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate_schema(data: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []

    def err(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    if "const" in schema and data != schema["const"]:
        err(f"必须为常量 {json.dumps(schema['const'], ensure_ascii=False)}，实际 {_type_name(data)}")
    if "enum" in schema and data not in schema["enum"]:
        err(f"值 {json.dumps(data, ensure_ascii=False)} 不在枚举 {json.dumps(schema['enum'], ensure_ascii=False)} 内")

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(data, t) for t in types):
            err(f"类型应为 {'/'.join(types)}，实际 {_type_name(data)}")
            return errors  # 类型错误时不继续深入，避免噪音

    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            err(f"长度 {len(data)} 小于 minLength={schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], data):
            err(f"不匹配 pattern {schema['pattern']!r}（实际 {data[:50]!r}）")

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            err(f"元素数 {len(data)} 小于 minItems={schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            err(f"元素数 {len(data)} 超过 maxItems={schema['maxItems']}")
        if "items" in schema:
            for i, item in enumerate(data):
                errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))

    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                err(f"缺少必备字段 {key!r}")
        props = schema.get("properties", {})
        addl = schema.get("additionalProperties", True)
        for key, value in data.items():
            if key in props:
                errors.extend(validate_schema(value, props[key], f"{path}.{key}"))
            elif addl is False:
                err(f"出现 schema 未定义字段 {key!r}（additionalProperties=false）")
            elif isinstance(addl, dict):
                errors.extend(validate_schema(value, addl, f"{path}.{key}"))
        for key, sub in props.items():
            if key in data:
                # 已在上面处理，这里不重复
                pass

    if "minimum" in schema and isinstance(data, (int, float)) and not isinstance(data, bool):
        if data < schema["minimum"]:
            err(f"值 {data} 小于 minimum={schema['minimum']}")
    if "maximum" in schema and isinstance(data, (int, float)) and not isinstance(data, bool):
        if data > schema["maximum"]:
            err(f"值 {data} 大于 maximum={schema['maximum']}")

    return errors


def load_schema(path: Optional[Path] = None) -> Dict[str, Any]:
    schema_path = path or SCHEMA_PATH
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    _apply_known_schema_deviations(schema)
    return schema


# KNOWN_SCHEMA_DEVIATION（MYW-58 显式记录，非静默）：
#   schema 将 private_markers.items.minLength 设为 4，但 T1 自己的 4 个黄金案例的
#   姓名标记（李晓晓=3 / 王成=2）都不满足，且 T1 执行口径（reference_score.py）
#   从不检查该项——中文姓名 2–3 字恰是隐私扫描最需要覆盖的内容，minLength=4
#   会迫使案例作者漏报短姓名。处理：仅当文件值仍为 4 时按 1 执行（不低于
#   minItems 的数组级约束），schema 修订后本覆盖自动失效。
PRIVATE_MARKER_MIN_LENGTH_OVERRIDE = 1


def _apply_known_schema_deviations(schema: Dict[str, Any]) -> None:
    pm = schema.get("properties", {}).get("private_markers")
    if isinstance(pm, dict):
        items = pm.get("items")
        if isinstance(items, dict) and items.get("minLength") == 4:
            items["minLength"] = PRIVATE_MARKER_MIN_LENGTH_OVERRIDE
            pm["deviation_note"] = (
                "MYW-58：文件原值 minLength=4 与 T1 黄金案例（李晓晓/王成）矛盾，"
                "validate_report 按 1 执行并已在 issue 报备；schema 修订后以文件为准"
            )


# ================= 算分核心（与 rubric 0.1.0 一致；score_report.py 复用） =================

def round_half_up(x: float) -> int:
    """四舍五入（半分位向上）。不用内建 round()（银行家舍入）。"""
    import math
    return int(math.floor(x + 0.5))


def counted_requirements(reqs: List[dict]) -> List[dict]:
    """未被去重合并的要求才进入计分（scoring-rubric.md §2 去重规则）。"""
    return [r for r in reqs if not r.get("merged_into")]


def score_of(job_id: str, reqs: List[dict]) -> Optional[int]:
    """score = floor(100 × Σ(w×coef)/Σ(w) + 0.5)；无可计要求返回 None。"""
    counted = counted_requirements([r for r in reqs if r["job_id"] == job_id])
    total_w = sum(WEIGHTS[r["importance"]] for r in counted)
    if not counted or total_w == 0:
        return None
    contrib = sum(WEIGHTS[r["importance"]] * COEFS[r["status"]] for r in counted)
    return round_half_up(100.0 * contrib / total_w)


def unknown_count_of(job_id: str, reqs: List[dict]) -> int:
    counted = counted_requirements([r for r in reqs if r["job_id"] == job_id])
    return sum(1 for r in counted if r["status"] in ("unclear", "unknown"))


def derive_suggestion(job: dict, reqs: List[dict]) -> str:
    """scoring-rubric.md §5 决策表，按序命中即停。hold 只能由已证实的 unmet 门槛触发。"""
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


# ================= 语义检查（引用 / 约束 / 决策表 / 隐私） =================

def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def check_share_privacy(data: dict) -> List[str]:
    """分享载荷隐私边界：private_markers / 邮箱 / 手机号扫描 + 与主目标分数一致。"""
    errors: List[str] = []
    sp = data["share_payload"]
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


def check_semantics(data: dict) -> List[str]:
    """结构层（schema）无法表达的跨字段约束。规则与 references/scoring-rubric.md 0.1.0 一致。"""
    errors: List[str] = []

    # 1. 版本常量（schema 已含 const，这里保留显式信息量更高的报错）
    if data["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version 应为 {SCHEMA_VERSION}，实际 {data['schema_version']}")
    if data["rubric_version"] != RUBRIC_VERSION:
        errors.append(f"rubric_version 应为 {RUBRIC_VERSION}，实际 {data['rubric_version']}")

    job_ids = {j["job_id"] for j in data["jobs"]}
    src_ids = {s["source_id"] for s in data["sources"]}
    ev_ids = {e["evidence_id"] for e in data["evidence"]}
    ans_ids = {a["answer_id"] for a in data["answers"]}
    req_ids = {r["req_id"] for r in data["requirements"]}

    # 2. 来源补充约束：补充回答必须与原简历区分（schema 已固定 recorded_as，这里查 applies_to_jobs）
    for a in data["answers"]:
        for jid in a["applies_to_jobs"]:
            if jid not in job_ids:
                errors.append(f"{a['answer_id']}: applies_to_jobs 无法解析 {jid}")

    # 3. 要求逐条：权重一致性、引用可解析、状态引用义务、去重标记
    for r in data["requirements"]:
        rid = r["req_id"]
        if r["weight"] != WEIGHTS[r["importance"]]:
            errors.append(f"{rid}: weight {r['weight']} 与 rubric 权重 {WEIGHTS[r['importance']]} 不一致")
        if r["job_id"] not in job_ids:
            errors.append(f"{rid}: job_id 无法解析 {r['job_id']}")
        for ev in r["evidence_ids"]:
            if ev not in ev_ids:
                errors.append(f"{rid}: evidence_id 无法解析 {ev}")
        for an in r["answer_ids"]:
            if an not in ans_ids:
                errors.append(f"{rid}: answer_id 无法解析 {an}")
        if r["status"] in ("supported", "partial") and not (r["evidence_ids"] or r["answer_ids"]):
            errors.append(f"{rid}: supported/partial 必须引用证据或补充回答，禁止无引用判断")
        if r["status"] == "unknown" and r.get("merged_into"):
            errors.append(f"{rid}: 被去重条目不应再有 unknown 状态")
        if "merged_into" in r and r["merged_into"] not in req_ids:
            errors.append(f"{rid}: merged_into 指向不存在的 req")
        # rationale 与 answers 无矛盾（MYW-69 重生成检查项）：材料里存在适用回答时，
        # rationale 不得断言「简历与回答均无记录」——回答按设计只进 answer_variants 也不行，
        # 措辞必须写成「简历正文无记录；追问回答是补充事实、计入需重跑」一类口径。
        if data["answers"]:
            job_answers = [a for a in data["answers"] if r["job_id"] in a["applies_to_jobs"]]
            if job_answers:
                for phrase in ("均无任何记录", "回答均无", "简历与回答均无"):
                    if phrase in r["rationale"]:
                        errors.append(
                            f"{rid}: rationale 与 answers 矛盾——存在适用回答 "
                            f"({','.join(a['answer_id'] for a in job_answers)})，"
                            f"但措辞出现「{phrase}」；补充事实未计入判定时应写明「按简历正文算，追问回答计入需重跑」"
                        )
                        break

    # 4. 门槛：unmet/met 必须有证据。unmet 禁止从缺失信息推断不满足；
    #    met 按 rubric §4 定义为「有证据满足」，无引用不得断言满足（MYW-62 补齐）。
    for job in data["jobs"]:
        for g in job["gates"]:
            if g["job_id"] != job["job_id"]:
                errors.append(f"{g['gate_id']}: gate.job_id 与所属岗位不一致")
            if g["status"] == "unmet" and not g.get("evidence_ids"):
                errors.append(f"{g['gate_id']}: unmet 门槛必须引用证据，禁止从缺失信息推断不满足")
            if g["status"] == "met" and not g.get("evidence_ids"):
                errors.append(f"{g['gate_id']}: met 门槛必须引用证据，禁止无引用的满足判断")
            for ev in g.get("evidence_ids", []):
                if ev not in ev_ids:
                    errors.append(f"{g['gate_id']}: evidence_id 无法解析 {ev}")

    # 5. 分数复算 + unknown_count + 建议决策表
    for job in data["jobs"]:
        if job["jd_source_id"] not in src_ids:
            errors.append(f"{job['job_id']}: jd_source_id 无法解析")
        derived = score_of(job["job_id"], data["requirements"])
        if job["scoring_status"] == "ok":
            if derived is None:
                errors.append(f"{job['job_id']}: scoring_status=ok 但无可计要求，应为 insufficient_input + score=null")
            elif job["score"] != derived:
                errors.append(f"{job['job_id']}: 分数不可复算 recorded={job['score']} derived={derived}")
        else:  # insufficient_input
            if job["score"] is not None:
                errors.append(f"{job['job_id']}: scoring_status=insufficient_input 时 score 必须为 null（不能伪装成 0 分）")
        if job["unknown_count"] != unknown_count_of(job["job_id"], data["requirements"]):
            errors.append(
                f"{job['job_id']}: unknown_count 与计算不一致 recorded={job['unknown_count']} "
                f"derived={unknown_count_of(job['job_id'], data['requirements'])}"
            )
        dsg = derive_suggestion(job, data["requirements"])
        if job["suggestion"] != dsg:
            errors.append(f"{job['job_id']}: 建议与决策表不一致 recorded={job['suggestion']} derived={dsg}")
        if "各自 JD 的证据覆盖" not in job["rank_rationale"]:
            errors.append(f"{job['job_id']}: rank_rationale 必须声明「各自 JD 的证据覆盖」口径")
        if job["scoring_status"] == "ok" and not isinstance(job["score"], int):
            errors.append(f"{job['job_id']}: score 必须为整数（禁止小数伪精度）")

    ranks = sorted(j["rank"] for j in data["jobs"])
    if ranks != list(range(1, len(data["jobs"]) + 1)):
        errors.append(f"rank 必须为 1..n 的排列，实际 {ranks}")
    if data["primary_job_id"] not in job_ids:
        errors.append("primary_job_id 无法解析")

    # 6. 改写：只属主目标；事实与待补字段齐备；无凑数
    for rw in data["rewrites"]:
        if rw["job_id"] != data["primary_job_id"]:
            errors.append(f"{rw['rewrite_id']}: 重点改写只属于主目标岗位")
        if rw["pending_fill"]:
            if "rewritten_text" in rw:
                errors.append(f"{rw['rewrite_id']}: 待补项不得产出可复制文本")
            if not rw.get("target_gap") or not rw.get("ask"):
                errors.append(f"{rw['rewrite_id']}: 待补项需 target_gap 与 ask")
        else:
            if not rw.get("original_quote") or not rw.get("rewritten_text"):
                errors.append(f"{rw['rewrite_id']}: 有效改写需 original_quote 与 rewritten_text")
        if "new_facts" not in rw:
            errors.append(f"{rw['rewrite_id']}: 必须声明 new_facts（纯润色为空）")
        for ev in rw.get("numbers_from", []):
            if ev not in ev_ids:
                errors.append(f"{rw['rewrite_id']}: numbers_from 无法解析 {ev}")
    effective = [rw for rw in data["rewrites"] if not rw["pending_fill"]]
    if len(effective) > 5:
        errors.append(f"有效改写 {len(effective)} 处超过 5 处上限")

    # 7. 行动：恰好 3 项，全部属主目标
    if len(data["actions"]) != 3:
        errors.append(f"主目标行动必须恰好 3 项，实际 {len(data['actions'])}")
    if [a["order"] for a in data["actions"]] != [1, 2, 3]:
        errors.append("行动 order 必须为 1,2,3")
    for a in data["actions"]:
        if a["job_id"] != data["primary_job_id"]:
            errors.append(f"{a['action_id']}: 行动只属主目标岗位")

    # 8. 补充回答变体：分数变化可复算且必须记录
    for var in data.get("answer_variants", []):
        for aid in var["answer_ids"]:
            if aid not in ans_ids:
                errors.append(f"answer_variants: answer_id 无法解析 {aid}")
        mutated = apply_variant(data, var)
        for job in mutated["jobs"]:
            derived = score_of(job["job_id"], mutated["requirements"])
            if job["job_id"] in var["job_scores"]:
                if var["job_scores"][job["job_id"]] != derived:
                    errors.append(
                        f"answer_variants[{var['answer_ids']}]: {job['job_id']} 变体分数不可复算 "
                        f"recorded={var['job_scores'][job['job_id']]} derived={derived}"
                    )
            elif derived != job["score"]:
                errors.append(f"answer_variants[{var['answer_ids']}]: {job['job_id']} 分数变化未记录")

    # 9. 分享载荷隐私
    errors.extend(check_share_privacy(data))

    # 10. 禁止伪精度/未校准置信度字段（防御性扫描；schema additionalProperties=false 为第一道防线）
    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(tok in k.lower() for tok in FORBIDDEN_KEY_TOKENS):
                    errors.append(f"禁止字段 {path}.{k}（未校准的置信度/ATS 分）")
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(data)

    # 11. 材料不足路径：无可判定要求时不得出分
    if not data["requirements"]:
        for job in data["jobs"]:
            if job["score"] is not None or job["scoring_status"] != "insufficient_input":
                errors.append(f"{job['job_id']}: 无可判定要求时不得出总分（不能伪装成 0 分）")

    return errors


# ================= 组合入口 =================

def check_report(data: Any, schema: Optional[Dict[str, Any]] = None) -> List[str]:
    """完整校验：schema 结构层 + 语义层。返回错误列表（空 = 通过）。"""
    if not isinstance(data, dict):
        return [f"顶层必须是 JSON 对象，实际 {_type_name(data)}"]
    schema_obj = schema if schema is not None else load_schema()
    errors = validate_schema(data, schema_obj)
    # 语义检查始终执行：即使结构有错也尽量给出全部问题，便于一次修复。
    try:
        errors.extend(check_semantics(data))
    except (KeyError, TypeError) as exc:
        errors.append(f"语义检查中止（结构错误导致）: {type(exc).__name__}: {exc}")
    return errors


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="T2 报告数据契约校验器（jd-match-report/0.1.0）")
    ap.add_argument("--input", metavar="FILE", required=True, help="待校验的报告 JSON 文件")
    ap.add_argument("--schema", metavar="FILE", default=None, help="覆盖默认 schema 路径（测试用）")
    ap.add_argument("--quiet", action="store_true", help="通过时不打印详情")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"✗ 输入文件不存在: {path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"✗ 输入不是合法 UTF-8 JSON: {exc}", file=sys.stderr)
        return 2

    schema_obj = load_schema(Path(args.schema)) if args.schema else load_schema()
    errors = check_report(data, schema_obj)

    if errors:
        print(f"契约校验失败（{len(errors)} 项）：")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    if not args.quiet:
        print(f"契约校验通过：{path}")
        print("  结构 = report-contract.schema.json；语义 = scoring-rubric.md 0.1.0（引用/决策表/隐私/伪精度）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
