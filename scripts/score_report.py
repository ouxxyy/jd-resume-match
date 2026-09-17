#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_report.py — T2 确定性评分脚本（唯一口径 jd-match-rubric/0.1.0）。

定位（重要）：
  * 分数、unknown_count、投递建议、排名全部由结构化判定确定性计算，
    模型/渲染器无另造总分之权。算法与 references/scoring-rubric.md 0.1.0
    及 T1 复算器 scripts/reference_score.py 同判（由 tests 固定）。
  * 评分前输出必须先通过 validate_report.check_report 的语义可解析检查；
    --apply 写回前必须通过完整契约校验，失败则不写盘（禁止产出非法报告）。

用法：
  # 核对：记录的分数/建议与脚本复算是否一致（不一致退出码 1）
  python3 scripts/score_report.py --check examples/case-a-freshgrad-ops/expected.json

  # 应用：用脚本复算值写回 score / unknown_count / suggestion / rank，
  # 并同时把每个岗位 rank_rationale 前置「各自 JD 的证据覆盖」口径（若缺失）。
  # 写盘前做完整契约校验，校验失败则拒绝写盘。
  python3 scripts/score_report.py --apply --input report.json --output report.scored.json

  # 逐项推导展示
  python3 scripts/score_report.py --show examples/case-a-freshgrad-ops/expected.json

退出码：0 = 成功；1 = 校验/复算不一致；2 = 用法/IO 错误。
仅依赖 Python 标准库（Python 3.9+）；不读取、不存储任何模型密钥。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_report import (  # noqa: E402
    COEFS, WEIGHTS, apply_variant, check_report, counted_requirements,
    derive_suggestion, load_schema, score_of, unknown_count_of,
)

RANK_RATIONALE_PHRASE = "各自 JD 的证据覆盖"


# ---- 推导表（供 --show 与 --check 输出） ----

def derive_table(data: dict) -> str:
    lines: List[str] = []
    for job in data["jobs"]:
        reqs = counted_requirements([r for r in data["requirements"] if r["job_id"] == job["job_id"]])
        lines.append(f"岗位 {job['job_id']}（{job['title']} / {job['category']}）scoring_status={job['scoring_status']}")
        tw = tc = 0.0
        for r in reqs:
            w = WEIGHTS[r["importance"]]
            c = COEFS[r["status"]]
            tw += w
            tc += w * c
            merge_note = f"  [已去重并入 {r['merged_into']}，退出计分]" if r.get("merged_into") else ""
            lines.append(f"  {r['req_id']:<14} {r['importance']:<6} w={w} {r['status']:<9} coef={c} 贡献={w*c:g}{merge_note}")
        if job["scoring_status"] == "ok":
            lines.append(
                f"  Σ权重={tw:g}  Σ贡献={tc:g}  分数=floor(100×{tc:g}/{tw:g}+0.5)="
                f"{score_of(job['job_id'], data['requirements'])}  记录={job['score']}"
            )
        else:
            lines.append("  信息不足路径：无可计要求，score=null（不伪装成 0 分）")
        for g in job["gates"]:
            lines.append(f"  门槛 {g['gate_id']}: {g['status']}")
        lines.append(
            f"  建议 derived={derive_suggestion(job, data['requirements'])} recorded={job['suggestion']}"
            f"  未知项={unknown_count_of(job['job_id'], data['requirements'])}"
        )
        lines.append("")
    for var in data.get("answer_variants", []):
        mutated = apply_variant(data, var)
        for jid, recorded in var["job_scores"].items():
            derived = score_of(jid, mutated["requirements"])
            lines.append(f"补充回答变体 {var['answer_ids']} → {jid}: derived={derived} recorded={recorded}")
    return "\n".join(lines)


# ---- 复算与核对 ----

def compute_job_fields(data: dict) -> Dict[str, Dict[str, Any]]:
    """按唯一口径推导每个岗位的派生字段（不改判断，只算分数/未知数/建议/排名）。"""
    derived: Dict[str, Dict[str, Any]] = {}
    for job in data["jobs"]:
        score = score_of(job["job_id"], data["requirements"])
        derived[job["job_id"]] = {
            "score": score if job["scoring_status"] == "ok" else None,
            "unknown_count": unknown_count_of(job["job_id"], data["requirements"]),
            "suggestion": derive_suggestion(job, data["requirements"]),
        }
    # 排名：全部岗位参与——分数降序（同分按输入顺序，并列分数相邻，rubric §6 允许并列）；
    # insufficient_input（无法评分）的岗位排在可评分岗位之后，按输入顺序。
    def rank_key(pair):
        idx, job, score = pair
        if score is None:
            return (1, 0, idx)
        return (0, -score, idx)

    for rank, (_, job, _) in enumerate(sorted(
            [(idx, job, score_of(job["job_id"], data["requirements"])
              if job["scoring_status"] == "ok" else None)
             for idx, job in enumerate(data["jobs"])],
            key=rank_key), start=1):
        derived[job["job_id"]]["rank"] = rank
    return derived


def mismatches(data: dict, derived: Dict[str, Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for job in data["jobs"]:
        jid = job["job_id"]
        d = derived[jid]
        if job["score"] != d["score"]:
            out.append(f"{jid}: score recorded={job['score']} derived={d['score']}")
        if job["unknown_count"] != d["unknown_count"]:
            out.append(f"{jid}: unknown_count recorded={job['unknown_count']} derived={d['unknown_count']}")
        if job["suggestion"] != d["suggestion"]:
            out.append(f"{jid}: suggestion recorded={job['suggestion']} derived={d['suggestion']}")
        if "rank" in d and job["rank"] != d["rank"]:
            out.append(f"{jid}: rank recorded={job['rank']} derived={d['rank']}（分数降序、同分按输入顺序）")
    return out


def apply_fields(data: dict, derived: Dict[str, Dict[str, Any]]) -> dict:
    """把派生字段写回数据（仅派生字段；状态判定与理由文本属于分析，不被脚本篡改）。

    share_payload.score 是主目标分数的镜像（契约要求两者一致），同为脚本派生值：
    补充回答改变主目标分数后由本函数同步，避免分析端留下过期镜像。
    """
    out = json.loads(json.dumps(data, ensure_ascii=False))
    primary = out.get("primary_job_id")
    for job in out["jobs"]:
        d = derived[job["job_id"]]
        job["score"] = d["score"]
        job["unknown_count"] = d["unknown_count"]
        job["suggestion"] = d["suggestion"]
        if "rank" in d:
            job["rank"] = d["rank"]
        if RANK_RATIONALE_PHRASE not in job["rank_rationale"]:
            job["rank_rationale"] = f"（{RANK_RATIONALE_PHRASE}口径，脚本按分数排序）" + job["rank_rationale"]
        if job["job_id"] == primary and isinstance(out.get("share_payload"), dict):
            out["share_payload"]["score"] = d["score"]
    return out


# ---- CLI ----

def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"✗ 输入不是合法 UTF-8 JSON: {exc}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="T2 确定性评分脚本（jd-match-rubric/0.1.0 唯一口径）")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", metavar="FILE", help="核对记录分数/建议与脚本复算是否一致")
    mode.add_argument("--apply", action="store_true", help="用复算值写回派生字段（需 --input/--output）")
    mode.add_argument("--show", metavar="FILE", help="打印逐项推导，不校验不写盘")
    ap.add_argument("--input", metavar="FILE", help="--apply 模式的输入报告 JSON")
    ap.add_argument("--output", metavar="FILE", help="--apply 模式的输出路径（不覆盖输入）")
    args = ap.parse_args(argv)

    if args.show:
        data = _load(Path(args.show))
        print(derive_table(data))
        return 0

    if args.check:
        path = Path(args.check)
        data = _load(path)
        contract_errors = check_report(data)
        derived = compute_job_fields(data)
        diffs = mismatches(data, derived)
        print(derive_table(data))
        if contract_errors or diffs:
            print(f"\n评分核对失败：契约错误 {len(contract_errors)} 项，复算不一致 {len(diffs)} 项：")
            for e in contract_errors:
                print(f"  ✗ [契约] {e}")
            for e in diffs:
                print(f"  ✗ [复算] {e}")
            return 1
        print(f"\n评分核对通过：{path} 的分数/未知数/建议/排名与 rubric 0.1.0 复算一致。")
        return 0

    # --apply
    if not args.input or not args.output:
        ap.error("--apply 需要 --input 与 --output（不覆盖输入文件）")
    in_path, out_path = Path(args.input), Path(args.output)
    data = _load(in_path)
    derived = compute_job_fields(data)
    diffs = mismatches(data, derived)
    if diffs:
        print(f"记录值与复算不一致 {len(diffs)} 项（将以脚本复算为准写回）：")
        for e in diffs:
            print(f"  → {e}")
    out_data = apply_fields(data, derived)
    errors = check_report(out_data)
    if errors:
        print(f"\n✗ 写盘被拒绝：应用复算值后契约校验仍失败（{len(errors)} 项）。请先修复分析数据，不要产出非法报告。")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n评分已按 rubric 0.1.0 复算并写回（契约校验通过）：{out_path}")
    for job in out_data["jobs"]:
        print(f"  {job['job_id']}: score={job['score']} unknown={job['unknown_count']} "
              f"rank={job['rank']} suggestion={job['suggestion']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
