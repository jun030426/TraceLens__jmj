"""Bounded recovery for PPT page receipts. Only complete specialist results are publishable."""
import copy
from pathlib import Path

from video_extraction.shared.common import read, signature

PAGE_HOLD_REASONS = {
    "invalid_model_response", "source_followup_issue_mapping",
    "source_followup_audit_changed", "source_followup_mapping_repair_changed",
}
LINK_HOLD_REASONS = {"invalid_model_response", "page_link_issue_mapping",
                     "duplicate_page_link", "page_link_wrong_scope"}


def hold_reasons(task):
    if task["kind"] == "visual" and task["unit"].get("source_kind") == "ppt":
        return PAGE_HOLD_REASONS
    if task["kind"] == "document_links" and all(p.get("source_kind") == "ppt" for p in task["pages"]):
        return LINK_HOLD_REASONS
    return ()


def compatible(plan, current):
    pins = read(Path(__file__).with_name("ppt_checkpoint_versions.json"))
    sources = plan["source_plan"]["sources"]
    return (bool(sources) and all(s["kind"] == "ppt" for s in sources)
            and signature(plan["code_hashes"]) in pins["previous"]
            and signature(current) == pins["current"])


def output_folder(folder, preferred, current, model, policy, source):
    if (preferred / "plan.json").exists():
        return preferred
    for plan_file in sorted(folder.glob("analysis-*/plan.json")):
        plan = read(plan_file)
        expected = "analysis-" + signature({"policy": policy, "engine": plan["code_hashes"], "model": model})[:20]
        if (plan_file.parent.name == expected and plan["source_plan"]["gemini_model"] == model
                and plan["source_plan"]["request"]["sources"] == [str(source.resolve())]):
            if compatible(plan, current):
                return plan_file.parent
            pins = read(Path(__file__).with_name("ppt_checkpoint_versions.json"))
            if signature(plan["code_hashes"]) in pins["previous"]:
                raise ValueError("DOCUMENT_CHECKPOINT_ENGINE_MISMATCH")
    return preferred


def normalized_layers(value):
    """Clip at most one integer edge per box, at most 12/1000 and 2% of its span."""
    fixed = copy.deepcopy(value)
    changes = []
    if not isinstance(fixed, dict):
        return value, []
    for layer in ("blocks", "visuals"):
        rows = fixed.get(layer, [])
        if not isinstance(rows, list):
            return value, []
        for index, row in enumerate(rows):
            box = row.get("bbox") if isinstance(row, dict) else None
            if not (isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box)):
                continue
            clipped = [max(0, min(1000, v)) for v in box]
            edges = [i for i in range(4) if box[i] != clipped[i]]
            if not edges:
                continue
            edge = edges[0]
            span = box[edge % 2 + 2] - box[edge % 2]
            delta = abs(box[edge] - clipped[edge])
            if (len(edges) != 1 or delta > 12 or 50 * delta > span
                    or clipped[0] >= clipped[2] or clipped[1] >= clipped[3]):
                return value, []
            changes.append({"layer": layer, "index": index, "before": box, "after": clipped})
            row["bbox"] = clipped
    return fixed, changes


def hold_file(out, task):
    return out / "ppt-holds" / (signature(task["id"])[:24] + ".json")


def bound_hold(plan_hash, task, retry_round, reason, results=None):
    marker = {"binding": signature({"plan": plan_hash, "task": task}), "round": retry_round, "reason": reason}
    if task["kind"] == "document_links":
        marker["pages"] = [p["location"]["page"] for p in task["pages"]]
        marker["page_receipts"] = [results[p["id"]]["payload_hash"] for p in task["pages"]]
    else:
        marker["page"] = task["unit"]["location"]["page"]
    return marker


def current_hold(out, plan_hash, task, retry_round, results=None):
    path = hold_file(out, task)
    if not path.exists():
        return None
    data = read(path)
    reason = data.get("reason")
    if reason not in hold_reasons(task):
        raise ValueError("invalid_page_hold")
    expected = bound_hold(plan_hash, task, data["round"], reason, results)
    if "page_receipts" in expected and data.get("page_receipts") != expected["page_receipts"]:
        return None
    if data != expected:
        raise ValueError("invalid_page_hold")
    return data if data["round"] == retry_round else None


def classified_holds(out, plan, results, retry_round):
    """Partial publication requires an explanation for every unfinished task."""
    missing = [t for t in plan["tasks"] if t["id"] not in results]
    held = {}
    plan_hash = signature(plan)
    for task in missing:
        if task["kind"] == "visual" and task["unit"].get("source_kind") == "ppt":
            marker = current_hold(out, plan_hash, task, retry_round)
            if marker:
                held[task["id"]] = marker
    for task in missing:
        if task["id"] in held:
            continue
        if task["kind"] == "document_links":
            parents = [p["id"] for p in task["pages"]]
            if all(i in results for i in parents):
                marker = current_hold(out, plan_hash, task, retry_round, results)
                if marker:
                    held[task["id"]] = marker
                    continue
            elif all(i in held or i in results for i in parents):
                continue
        return []
    return list(held.values())


def hold_link_dependents(rows, pending_links):
    """A missing pair cannot settle a coverage issue or support dependent records."""
    if not pending_links:
        return
    page_ids = {p["id"] for task in pending_links for p in task["pages"]}
    relation_prefixes = tuple(task["pages"][0]["id"] + ":page-link:" for task in pending_links)
    blocked = {task["id"] for task in pending_links}
    blocked.update(row["id"] for row in rows if row.get("unit_id") in page_ids
                   and "pdf_cross_page_connection_requires_review" in row.get("reasons", []))
    while True:
        dependents = {r["id"] for r in rows if any(ref in blocked or ref.startswith(relation_prefixes)
                      for ref in r.get("related_record_ids", []))}
        if dependents <= blocked:
            break
        blocked.update(dependents)
    for row in rows:
        if row["id"] in blocked:
            row.update(eligible_for_chunking=False, approved_for_rag=False, judgment="held")
            row.pop("low_impact_warning", None)
            row["reasons"] = sorted(set(row.get("reasons", [])) | {"page_link_review_pending"})
