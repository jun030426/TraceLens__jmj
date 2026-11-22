"""Bounded recovery for PPT page receipts. Only complete specialist results are publishable."""
import copy
from pathlib import Path

from video_extraction.shared.common import read, signature

PAGE_HOLD_REASONS = {
    "invalid_model_response", "source_followup_issue_mapping",
    "source_followup_audit_changed", "source_followup_mapping_repair_changed",
}


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


def bound_hold(plan_hash, task, retry_round, reason):
    return {"binding": signature({"plan": plan_hash, "task": task}), "round": retry_round,
            "page": task["unit"]["location"]["page"], "reason": reason}


def current_hold(out, plan_hash, task, retry_round):
    path = hold_file(out, task)
    if not path.exists():
        return None
    data = read(path)
    reason = data.get("reason")
    if reason not in PAGE_HOLD_REASONS:
        raise ValueError("invalid_page_hold")
    expected = bound_hold(plan_hash, task, data["round"], reason)
    if data != expected:
        raise ValueError("invalid_page_hold")
    return data if data["round"] == retry_round else None


def classified_holds(out, plan, results, retry_round):
    """Return holds only when every pending task is a held page or a dependent link."""
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
        if task["kind"] != "document_links" or not any(p["id"] in held for p in task["pages"]):
            return []
        if any(p["id"] not in results and p["id"] not in held for p in task["pages"]):
            return []
    return list(held.values())
