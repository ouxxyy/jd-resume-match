#!/usr/bin/env python3
"""jd-resume-match MCP Server（stdio JSON-RPC 2.0）。

只暴露一个核心工具：`match_resume(jd, resume)`
输出：按 `jd-match-rubric/0.1.0` 公式确定性复算的匹配分数、逐条 JD 要求的简历原文行号证据引用与证据缺口清单。
安全承诺：纯本地计算，零网络请求，不上传任何简历或 JD 数据。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any

RUBRIC_VERSION = "jd-match-rubric/0.1.0"
WEIGHTS = {"core": 3, "bonus": 1}
COEFS = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0, "unknown": 0.0}

BONUS_KEYWORDS = ("加分", "优先", "plus", "preferred", "bonus", "更佳")
REQ_SPLIT_RE = re.compile(r"[\r\n]+|[；;。！？!?]+")
CN_CONNECTOR_RE = re.compile(
    r"(?:熟悉|精通|负责|参与|具备|具有|了解|掌握|能够|善于|独立|完成|推进|搭建|落地|经验|优先|加分项|加分|能力|相关|以上|[的与及和并或有能在对从将把为中：:、，,（）()])"
)
TOKEN_RE = re.compile(r"[A-Za-z0-9\+\#\.]{2,}|[\u4e00-\u9fff]{2,5}")

STOPWORDS = {
    "工作", "岗位", "要求", "任职", "资格", "职责", "描述", "我们", "团队", "进行", "日常",
    "以及", "或者", "并且", "使用", "支持", "定位", "提升",
}


def _extract_tokens(text: str) -> list[str]:
    """提取用于证据定位的中英文关键短语与技术词。"""
    cleaned = CN_CONNECTOR_RE.sub(" ", text)
    raw = TOKEN_RE.findall(cleaned)
    out: list[str] = []
    for tok in raw:
        low = tok.lower()
        if low in STOPWORDS or len(low) < 2:
            continue
        if low not in out:
            out.append(low)
    return out


def _split_jd_requirements(jd_text: str) -> list[dict[str, Any]]:
    """将 JD 文本拆解为结构化要求列表，区分 core（核心，权重 3）与 bonus（加分，权重 1）。"""
    chunks = [c.strip(" \t-•*0123456789.、()（）[]【】") for c in REQ_SPLIT_RE.split(jd_text)]
    reqs: list[dict[str, Any]] = []
    for chunk in chunks:
        if len(chunk) < 6:
            continue
        tokens = _extract_tokens(chunk)
        if not tokens:
            continue
        is_bonus = any(k in chunk.lower() for k in BONUS_KEYWORDS)
        req_id = f"req-{len(reqs) + 1:02d}"
        reqs.append(
            {
                "req_id": req_id,
                "text": chunk,
                "importance": "bonus" if is_bonus else "core",
                "tokens": tokens,
            }
        )
    return reqs


def match_resume(jd: str, resume: str) -> dict[str, Any]:
    """根据 jd-match-rubric/0.1.0 对 JD 与简历进行行级证据定位与可复算评分。"""
    jd_clean = (jd or "").strip()
    resume_clean = (resume or "").strip()
    if not jd_clean or not resume_clean:
        return {
            "rubric_version": RUBRIC_VERSION,
            "scoring_status": "insufficient_input",
            "score": None,
            "formula": "floor(100 * sum(weight * coef) / sum(weight) + 0.5)",
            "message": "JD 或简历文本为空，无法按证据评分（按规范返回 null，不伪装成 0 分）。",
            "requirements": [],
            "evidence_gaps": [],
        }

    resume_lines = [
        {"line_no": f"L{idx}", "text": line.strip()}
        for idx, line in enumerate(resume_clean.splitlines(), start=1)
        if line.strip()
    ]
    reqs = _split_jd_requirements(jd_clean)
    if not reqs:
        return {
            "rubric_version": RUBRIC_VERSION,
            "scoring_status": "insufficient_input",
            "score": None,
            "formula": "floor(100 * sum(weight * coef) / sum(weight) + 0.5)",
            "message": "未能在 JD 中识别出可核对的具体要求条款。",
            "requirements": [],
            "evidence_gaps": [],
        }

    evaluated: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    total_weight = 0.0
    total_contrib = 0.0

    for req in reqs:
        tokens = req["tokens"]
        best_line = None
        best_hits: list[str] = []
        all_matched_tokens: set[str] = set()

        for rline in resume_lines:
            low_line = rline["text"].lower()
            hits = [t for t in tokens if t in low_line]
            if hits:
                all_matched_tokens.update(hits)
                if len(hits) > len(best_hits):
                    best_hits = hits
                    best_line = rline

        coverage = len(all_matched_tokens) / max(len(tokens), 1)
        if coverage >= 0.5 or len(best_hits) >= 2:
            status = "supported"
        elif coverage > 0:
            status = "partial"
        else:
            status = "unsupported"

        weight = WEIGHTS[req["importance"]]
        coef = COEFS[status]
        contrib = weight * coef
        total_weight += weight
        total_contrib += contrib

        citation = (
            {
                "source_id": "src-resume-1",
                "locator": best_line["line_no"],
                "quote": best_line["text"][:160],
                "matched_keywords": best_hits,
            }
            if best_line
            else None
        )

        evaluated.append(
            {
                "req_id": req["req_id"],
                "requirement": req["text"],
                "importance": req["importance"],
                "weight": weight,
                "status": status,
                "coef": coef,
                "contribution": contrib,
                "evidence": citation,
            }
        )

        if status != "supported":
            missing = [t for t in tokens if t not in all_matched_tokens]
            gaps.append(
                {
                    "req_id": req["req_id"],
                    "requirement": req["text"],
                    "status": status,
                    "missing_signals": "、".join(missing[:6]) or "缺少具体行动、指标或结果证据",
                }
            )

    score = math.floor(100.0 * total_contrib / total_weight + 0.5) if total_weight > 0 else None
    return {
        "rubric_version": RUBRIC_VERSION,
        "scoring_status": "ok",
        "score": score,
        "total_weight": total_weight,
        "total_contribution": total_contrib,
        "formula": f"floor(100 * {total_contrib:g} / {total_weight:g} + 0.5) = {score}",
        "privacy_notice": "本工具在本地进程内完成证据比对与复算，不发起任何网络请求，不上传简历与 JD。",
        "suite_url": "https://github.com/ouxxyy/ouba-classmate",
        "requirements": evaluated,
        "evidence_gaps": gaps,
    }


TOOL_SPEC = {
    "name": "match_resume",
    "description": (
        "按 jd-match-rubric/0.1.0 规则对岗位 JD 与候选人简历进行确定性评分与行级证据引用。"
        "返回可复算分数（score）、权重推导公式、每条 JD 要求对应的简历原文行号引用（L1..Ln）及证据缺口清单。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "jd": {
                "type": "string",
                "description": "目标岗位 JD 原文文本",
            },
            "resume": {
                "type": "string",
                "description": "候选人简历纯文本内容",
            },
        },
        "required": ["jd", "resume"],
    },
}


def handle_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
    """处理单条 MCP JSON-RPC 2.0 消息。"""
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "io.github.ouxxyy/jd-resume-match",
                    "version": "0.1.0",
                },
            },
        }
    if method and method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": [TOOL_SPEC]},
        }
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "match_resume":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"未知工具: {name}"},
            }
        result = match_resume(
            jd=str(arguments.get("jd", "")),
            resume=str(arguments.get("resume", "")),
        )
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": False,
            },
        }
    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"不支持的方法: {method}"},
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="jd-resume-match MCP Server (stdio)")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行内置合成数据自检并打印 JSON 结果后退出",
    )
    args = parser.parse_args()

    if args.self_test:
        sample_jd = (
            "1. 负责 AI Agent 产品规划与跨团队推进，有大模型应用落地经验；\n"
            "2. 熟悉评测体系搭建与数据分析，能定位 badcase 并提升准确率；\n"
            "3. 加分项：有开源项目或 MCP 工具开发经验优先。"
        )
        sample_resume = (
            "2024-2026 某互联网公司 高级产品经理\n"
            "独立负责企业级 AI Agent 知识库产品规划，跨团队协同研发上线，覆盖 12 个业务部门。\n"
            "搭建 300 条黄金测试集与自动化评测体系，通过 badcase 归因将回答准确率从 68% 提升至 89%。"
        )
        res = match_resume(sample_jd, sample_resume)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("score") is not None else 1

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_rpc(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
