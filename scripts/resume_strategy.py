"""整份简历策略的结构与语义校验；口径见 references/analysis-strategy.md。

不计算评分。结构直接消费 editorial.schema.json；证据仍来自评分报告。
"""
import json
from collections import defaultdict
from pathlib import Path

from validate_report import EMAIL_RE, PHONE_RE, validate_schema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "references/editorial.schema.json"


def validate_editorial_structure(ed):
    """解析本地 $ref 并检查 Schema，含本契约使用的根层 if/then。"""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def resolve(node):
        if isinstance(node, list):
            return [resolve(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = schema
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return resolve(target)
        return {k: resolve(v) for k, v in node.items() if k not in ("definitions", "allOf")}

    errors = validate_schema(ed, resolve(schema))
    for rule in schema.get("allOf", []):
        if not validate_schema(ed, resolve(rule["if"])):
            errors.extend(validate_schema(ed, resolve(rule["then"])))
    return errors


def validate_resume_strategy(report, strategy, *, digits_of, scope_words, voice_lint, ed_rewrites=()):
    """已过结构校验后，检查层级、全量取舍、引用和同经历事实归属。

    数字出处只证明词面存在；因果、单位、个人/团队归属仍须按分析规范审阅。
    """
    errors = []
    items = {x["item_id"]: x for x in strategy["inventory"]}
    evs = {x["evidence_id"]: x for x in report["evidence"]}
    answers = {x["answer_id"]: x for x in report["answers"]}
    reqs = {x["req_id"]: x for x in report["requirements"] if not x.get("merged_into")}
    rws = {x["rewrite_id"]: x for x in report["rewrites"] if not x.get("pending_fill")}
    after_overrides = {x["rewrite_id"]: x.get("after_text") for x in ed_rewrites}
    resume_sources = {x["source_id"] for x in report["sources"] if x["kind"] == "resume"}
    primary = report["primary_job_id"]

    def err(where, message):
        errors.append(f"resume_strategy.{where}: {message}")

    def unique(values, where):
        if len(values) != len(set(values)):
            err(where, "重复引用/编号")

    def check_refs(value, where):
        # analysis-strategy §数据约束：只引用未合并的主目标要求。
        for rid in value.get("req_ids", []):
            if rid not in reqs or reqs[rid]["job_id"] != primary:
                err(where, f"要求无法解析或不属于主目标 {rid}")
        for eid in value.get("evidence_ids", []):
            if eid not in evs:
                err(where, f"证据无法解析 {eid}")

    def declared_pool(value, item_ids=()):
        eids = set(value.get("evidence_ids", []))
        for iid in item_ids:
            if iid in items:
                eids.update(items[iid]["evidence_ids"])
        return " ".join([evs[e]["quote"] for e in eids if e in evs]
                        + [reqs[r]["jd_quote"] for r in value.get("req_ids", []) if r in reqs]
                        + [answers[a]["answer"] for a in value.get("answer_ids", []) if a in answers])

    def prose(value, pool, where):
        check_text(value, pool, where, factual=False, errors=errors,
                   digits_of=digits_of, scope_words=scope_words, voice_lint=voice_lint)

    unique([x["item_id"] for x in strategy["inventory"]], "inventory")
    if strategy["job_id"] != primary:
        err("job_id", "必须对应主目标岗位")
    children = defaultdict(list)
    for item in strategy["inventory"]:
        iid, kind, parent = item["item_id"], item["kind"], item["parent_id"]
        children[parent].append(item)
        expected = {"section": None, "entry": "section", "bullet": "entry"}[kind]
        if kind == "section":
            if parent is not None:
                err(iid, "模块 parent_id 必须为 null")
        elif parent not in items or items[parent]["kind"] != expected:
            err(iid, "父级不存在或层级错误（模块→经历→条目）")
        if kind == "entry" and "entry_kind" not in item:
            err(iid, "经历必须声明 entry_kind")
        if kind != "entry" and "entry_kind" in item:
            err(iid, "entry_kind 仅可用于经历")
        if item.get("entry_kind") in ("work", "internship") and item["disposition"] == "omit":
            err(iid, "工作/实习任职信息必须保留，可压缩职责而非删除任职")
        if EMAIL_RE.search(item["raw_quote"]) or PHONE_RE.search(item["raw_quote"]):
            err(iid, "联系方式不进入全篇库存")
        unique(item["evidence_ids"], iid)
        for eid in item["evidence_ids"]:
            if eid not in evs or evs[eid]["source_id"] not in resume_sources:
                err(iid, f"简历证据无法解析 {eid}")
        pool = " ".join(evs[e]["quote"] for e in item["evidence_ids"] if e in evs)
        if not any(item["raw_quote"] in evs[e]["quote"] for e in item["evidence_ids"] if e in evs):
            err(iid, "raw_quote 必须是所引简历证据的逐字连续子串")
        if item.get("entry_kind") in ("work", "internship") and not any(item["raw_quote"] == evs[e]["quote"] for e in item["evidence_ids"] if e in evs):
            err(iid, "工作/实习 raw_quote 必须保留完整任职引文，不可裁掉雇主、职位或日期")
        check_text(item["label"], pool, iid + ".label", factual=True,
                   errors=errors, digits_of=digits_of, scope_words=scope_words, voice_lint=voice_lint)
        prose(item["rationale"], declared_pool(item), iid + ".rationale")
        check_refs(item, iid)

    for parent, siblings in children.items():
        if sorted(x["original_order"] for x in siblings) != list(range(1, len(siblings) + 1)):
            err("inventory", f"父级 {parent} 的原始顺序必须唯一且连续")

    def entry_of(iid):
        item = items.get(iid)
        if item and item["kind"] == "entry":
            return iid
        if item and item["kind"] == "bullet":
            parent = items.get(item["parent_id"])
            return parent["item_id"] if parent and parent["kind"] == "entry" else None
        return None

    owners = defaultdict(set)
    for item in items.values():
        entry = entry_of(item["item_id"])
        if entry:
            for eid in item["evidence_ids"]:
                owners[eid].add(entry)
    for eid, entries in owners.items():
        if len(entries) > 1:
            err("inventory", f"证据 {eid} 同时归属不同经历，须拆分引文")

    answer_entries = defaultdict(set)
    links = [(x["answer_id"], x["entry_id"]) for x in strategy["answer_links"]]
    unique(links, "answer_links")
    for aid, entry in links:
        if aid not in answers or primary not in answers[aid]["applies_to_jobs"]:
            err("answer_links", f"回答 {aid} 不适用于主目标")
        if entry not in items or items[entry]["kind"] != "entry":
            err("answer_links", f"经历 {entry} 无法解析")
        answer_entries[aid].add(entry)

    def claim(c, where, entry=None, business=False):
        check_refs(c, where)
        for iid in c["item_ids"]:
            if iid not in items:
                err(where, f"库存位置无法解析 {iid}")
        for aid in c["answer_ids"]:
            if aid not in answers or primary not in answers[aid]["applies_to_jobs"]:
                err(where, f"回答无法解析或不适用 {aid}")
            if entry and entry not in answer_entries[aid]:
                err(where, "经历事实引用回答前必须声明相应 answer_links")
        if not (c["req_ids"] or c["evidence_ids"] or c["answer_ids"] or c["item_ids"]):
            err(where, "判断必须声明原文/要求/位置锚点")
        if business and c["basis"] == "fact":
            err(where, "招聘业务问题只能标为推断或待确认")
        if c["basis"] == "fact" and not (c["evidence_ids"] or c["answer_ids"] or c["req_ids"]):
            err(where, "事实不能仅凭位置标签断言，必须引用原文")
        if entry and c["basis"] == "fact" and not (c["evidence_ids"] or c["answer_ids"]):
            err(where, "本人经历事实必须引用该经历的简历证据或已关联回答，JD 不能证明经历")
        evidence_ids = set(c["evidence_ids"])
        for iid in c["item_ids"]:
            if iid in items:
                evidence_ids.update(items[iid]["evidence_ids"])
        if entry:
            for eid in evidence_ids:
                if owners[eid] != {entry}:
                    err(where, f"跨经历事实引用 {eid}，不得拼接其他经历")
            for iid in c["item_ids"]:
                if entry_of(iid) != entry:
                    err(where, "经历价值链的位置必须属于同一经历")
        pool = " ".join(evs[e]["quote"] for e in evidence_ids if e in evs)
        pool += " " + " ".join(answers[a]["answer"] for a in c["answer_ids"] if a in answers)
        # JD 只可为诊断/推断提供措辞依据，不能证明本人经历的数字与职责。
        if entry is None:
            pool += " " + " ".join(reqs[r]["jd_quote"] for r in c["req_ids"] if r in reqs)
        check_text(c["text"], pool, where, factual=c["basis"] == "fact",
                   errors=errors, digits_of=digits_of, scope_words=scope_words, voice_lint=voice_lint)

    seen = []
    for section in strategy["blueprint"]:
        sid = section["section_id"]
        seen.append(sid)
        if sid not in items or items[sid]["kind"] != "section":
            err("blueprint", f"模块 {sid} 无法解析")
        section_ids = [sid] + [e["entry_id"] for e in section["entries"]]
        for e in section["entries"]:
            section_ids.extend(e["bullet_ids"])
        prose(section["rationale"], declared_pool({}, section_ids), "blueprint.rationale")
        for entry in section["entries"]:
            eid = entry["entry_id"]
            seen.append(eid)
            if eid not in items or items[eid]["kind"] != "entry":
                err("blueprint", f"经历 {eid} 无法解析")
            prose(entry["rationale"], declared_pool({}, [eid] + entry["bullet_ids"]), "blueprint.entry.rationale")
            for bid in entry["bullet_ids"]:
                seen.append(bid)
                if bid not in items or items[bid]["kind"] != "bullet" or items[bid]["parent_id"] != eid:
                    err("blueprint", f"条目 {bid} 不属于该经历，不能跨经历移动")
    unique(seen, "blueprint")
    expected = {iid for iid, x in items.items() if x["disposition"] != "omit"}
    if set(seen) != expected:
        err("blueprint", "保留项有遗漏或含已删除项；所有库存项都必须有明确去向")

    concepts = [x["concept"].strip().casefold() for x in strategy["job_focus"]]
    unique(concepts, "job_focus")
    for i, focus in enumerate(strategy["job_focus"]):
        where = f"job_focus[{i}]"
        check_refs(focus, where)
        if not any(focus["jd_quote"] in reqs[r]["jd_quote"] for r in focus["req_ids"] if r in reqs):
            err(where, "jd_quote 必须是所引 JD 要求的逐字连续子串")
        prose(focus["concept"], declared_pool(focus), where + ".concept")
        claim(focus["business_problem"], where + ".business_problem", business=True)

    insight_entries = []
    for i, insight in enumerate(strategy["experience_insights"]):
        entry = insight["entry_id"]
        insight_entries.append(entry)
        if entry not in items or items[entry]["kind"] != "entry":
            err("experience_insights", "价值链必须属于库存经历")
        for field in ("problem", "role", "actions", "outputs", "changes", "skills", "impact"):
            claim(insight[field], f"experience_insights[{i}].{field}", entry=entry)
    unique(insight_entries, "experience_insights")
    review = strategy["recruiter_review"]
    for field in ("first_impression", "buried_evidence", "generic_statements"):
        for i, c in enumerate(review[field]):
            claim(c, f"recruiter_review.{field}[{i}]")
    for i, concern in enumerate(review["concerns"]):
        claim(concern["observation"], f"recruiter_review.concerns[{i}]")
        observation = concern["observation"]
        if not observation["item_ids"] or not (observation["evidence_ids"] or observation["answer_ids"]):
            err(f"recruiter_review.concerns[{i}]", "筛选疑虑必须有简历/回答原文依据及具体库存位置，不能只引 JD")
        for field in ("interview_question", "change"):
            c = concern["observation"]
            prose(concern[field], declared_pool(c, c["item_ids"]), f"recruiter_review.concerns[{i}].{field}")
    ats = strategy["ats_review"]
    for i, keyword in enumerate(ats["keywords"]):
        check_refs(keyword, f"ats_review.keywords[{i}]")
        claim(keyword["observation"], f"ats_review.keywords[{i}].observation")
        prose(keyword["concept"], declared_pool(keyword), f"ats_review.keywords[{i}].concept")
        if keyword["status"] != "missing_evidence" and not (keyword["observation"]["evidence_ids"] or keyword["observation"]["answer_ids"]):
            err(f"ats_review.keywords[{i}]", "声称已有/同义/未写清的经验必须引用简历或回答")
    for field in ("readability", "format_observations"):
        for i, c in enumerate(ats[field]):
            claim(c, f"ats_review.{field}[{i}]")
    if ats["format_status"] != "visual_checked" and any(c["basis"] == "fact" for c in ats["format_observations"]):
        err("ats_review.format_observations", "未见原始视觉版式，只能记录未核验项")

    revisions = strategy["revision_priorities"]
    if [x["order"] for x in revisions] != list(range(1, len(revisions) + 1)):
        err("revision_priorities", "修改优先级编号必须按展示顺序连续")
    rewrite_entries = {}
    for i, revision in enumerate(revisions):
        where = f"revision_priorities[{i}]"
        claim(revision["impact"], where + ".impact")
        prose(revision["change"], declared_pool(revision["impact"], revision["location_item_ids"]), where + ".change")
        for iid in revision["location_item_ids"]:
            if iid not in items:
                err(where, f"修改位置无法解析 {iid}")
        unique(revision["rewrite_ids"], where)
        for rid in revision["rewrite_ids"]:
            if rid not in rws:
                err(where, "有效改写无法解析")
                continue
            visible_locations = [items[i] for i in revision["location_item_ids"] if i in items and i in seen]
            matching_bullets = [x for x in visible_locations if x["kind"] == "bullet" and rws[rid]["original_quote"] in x["raw_quote"]]
            if not matching_bullets:
                err(where, "改写必须关联蓝图中保留的原条目，不能改写已删除项")
                continue
            entries = {entry_of(x["item_id"]) for x in matching_bullets}
            if len(entries) != 1:
                err(where, "有效改写必须关联唯一的所属经历")
                continue
            entry = next(iter(entries))
            if rid in rewrite_entries and rewrite_entries[rid] != entry:
                err(where, "同一改写不能属于不同经历")
            rewrite_entries[rid] = entry
            pool = " ".join(evs[e]["quote"] for e, own in owners.items() if own == {entry} and e in evs)
            pool += " " + " ".join(answers[a]["answer"] for a, own in answer_entries.items() if entry in own and a in answers)
            rw = rws[rid]
            if rw["original_quote"] not in pool:
                err(where, "改前引文不属于所关联的经历")
            for ev in rw.get("numbers_from", []):
                if owners[ev] != {entry}:
                    err(where, "改写数字出处跨经历")
            check_text(after_overrides.get(rid) or rw["rewritten_text"], pool, where + ".rewrite", factual=True,
                       errors=errors, digits_of=digits_of, scope_words=scope_words, voice_lint=voice_lint)
    if set(rewrite_entries) != set(rws):
        err("revision_priorities", "必须覆盖全部有效改写，并关联所属经历")
    for i, fact in enumerate(strategy["missing_facts"]):
        check_refs(fact, f"missing_facts[{i}]")
        for iid in fact["item_ids"]:
            if iid not in items:
                err("missing_facts", f"待补位置无法解析 {iid}")
        if not (fact["item_ids"] or fact["req_ids"]):
            err("missing_facts", "待补事实必须关联位置或要求")
        for field in ("gap", "ask", "where_to_find"):
            prose(fact[field], declared_pool(fact, fact["item_ids"]), "missing_facts." + field)
    return errors


def check_text(text, pool, where, *, factual, errors, digits_of, scope_words, voice_lint):
    """复用渲染器的表达检查、数字提取和职责词定义，避免第二套口径。"""
    voice_lint(errors, "resume_strategy." + where, text)
    for num in digits_of(text):
        if num not in set(digits_of(pool)):
            errors.append(f"resume_strategy.{where}: 数字「{num}」在声明的证据范围内无出处")
    if factual:
        for word in scope_words:
            if word in text and word not in pool:
                errors.append(f"resume_strategy.{where}: 新增职责范围词「{word}」")
