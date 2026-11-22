"""Synthetic delayed transport. Exercise task ordering, admission and durable replay."""
import io
import json
import threading
import time
from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from lerny.inference import current_job, job_context
from video_extraction.pipeline import connected
from video_extraction.shared.common import read, signature
from video_extraction.shared.gemini import Blocked


def exercise(folder, concurrency, monkeypatch, *, interrupt=False, maximum=100):
    units = [{"id": f"p{n}", "source_kind": "ppt", "location": {"page": n}} for n in range(1, 9)]
    tasks = [{"id": p["id"], "kind": "visual", "unit": p} for p in units]
    tasks += [{"id": f"link{n}", "kind": "document_links", "pages": units[n:n+2]} for n in range(7)]
    plan = {"tasks": tasks, "source_plan": {"gemini_model": "fixture"}}
    monkeypatch.setenv("LERNY_GEMINI_API_KEY", "synthetic-only")
    monkeypatch.setattr(connected, "lock", lambda _: nullcontext())
    monkeypatch.setattr(connected, "verify", lambda _: plan)
    monkeypatch.setattr(connected, "revalidate_result", lambda *_: None)
    monkeypatch.setattr(connected.runtime_tools, "audit", lambda *_: {"checks": [], "core_ready": True})
    def publish(*_):
        ready = connected.done(folder, plan)
        return {"pending": len(tasks)-len(ready), "all_tasks_processed": len(tasks)==len(ready)}
    monkeypatch.setattr(connected, "publish", publish)
    monkeypatch.setattr(connected.alignment_bridge, "run", lambda *_: {
        "state":"not_required", "targets":0, "pending_or_unresolved":0, "records_with_timing":0})
    counters = Counter()
    calls = Counter()
    mutex = threading.Lock()
    schema = {"type": "boolean"}
    def transport(request, timeout):
        assert current_job() == ("synthetic", 0)
        key = json.loads(request.data)["input"][0]["text"]
        with mutex:
            calls[key] += 1
            counters["active"] += 1
            counters["peak"] = max(counters["peak"], counters["active"])
        try:
            time.sleep(0.065)
            return io.BytesIO(b'{"status":"completed","output_text":"true"}')
        finally:
            with mutex:
                counters["active"] -= 1
    def visual(unit, plan, target, client, context):
        if interrupt and unit["id"] == "p6":
            raise Blocked("operator_stop")
        client.call("read", [], unit["id"], schema)
        # Different pages may issue the identical paid request.
        client.call("shared", [], "identical", schema)
        return {"records": [], "changes": []}
    def links(task, results, target, client):
        for page in task["pages"]:
            assert page["id"] in results
            assert (folder/"results"/(signature(page["id"])[:24]+".json")).is_file()
        for phase in ("read", "verify"):
            client.call("link-"+phase, [], task["id"]+phase, schema)
        return {"records": [], "changes": []}
    monkeypatch.setattr(connected, "visual", visual)
    monkeypatch.setattr(connected.document_links, "run", links)
    start = time.monotonic()
    with job_context(SimpleNamespace(id="synthetic", payload={})):
        if interrupt or maximum < 20:
            with pytest.raises(Blocked):
                connected.run(folder, None, maximum=maximum, delay=0, transport=transport,
                              ppt_retry_round=1, review_concurrency=concurrency)
        else:
            assert connected.run(folder, None, maximum=maximum, delay=0, transport=transport,
                                 ppt_retry_round=1, review_concurrency=concurrency)["all_tasks_processed"]
    elapsed = time.monotonic()-start
    return calls, counters["peak"], elapsed, set(connected.done(folder, plan))


def test_four_slots_reduce_wall_time_preserve_dependencies_and_deduplicate(tmp_path, monkeypatch):
    serial, one, serial_time, _ = exercise(tmp_path/"serial", 1, monkeypatch)
    parallel, four, parallel_time, completed = exercise(tmp_path/"four", 4, monkeypatch)
    assert serial == parallel and len(completed) == 15
    assert sum(parallel.values()) == 23 and parallel["identical"] == 1
    assert one == 1 and four == 4 and parallel_time < serial_time * 0.8
    print(f"serial={serial_time:.3f}s parallel={parallel_time:.3f}s peaks={one},{four}")


def test_stopped_run_keeps_every_completed_page_free_on_resume(tmp_path, monkeypatch):
    calls, peak, _, saved = exercise(tmp_path, 4, monkeypatch, interrupt=True)
    assert saved and len(saved)<8 and peak <= 4
    resumed, _, _, all_done = exercise(tmp_path, 4, monkeypatch)
    assert len(all_done) == 15 and all(resumed[p] == 0 for p in saved)
    assert sum((calls+resumed).values()) == 23
    assert sum(exercise(tmp_path, 4, monkeypatch)[0].values()) == 0


def test_parallel_run_cannot_overspend_budget(tmp_path, monkeypatch):
    calls, peak, _, _ = exercise(tmp_path, 4, monkeypatch, maximum=5)
    assert sum(calls.values()) == 5 and peak <= 4
    [log] = (tmp_path/"runs").glob("*.json")
    assert [row["attempt"] for row in read(log)["attempts"]] == list(range(1,6))
