"""Anonymized structural excerpts; no source slide, transcript, key or live transport."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lerny.gemini_failures import prepare_retry
from video_extraction.pipeline import connected, source_followup
from video_extraction.shared.common import digest_file, read, save, signature, validate
from video_extraction.shared.gemini import Blocked, Gemini
from video_extraction.video.vision_layers import EXTRACT

FIXTURE = read(Path(__file__).parent / "fixtures/ppt_recovery.json")


def layers(count, box=(100, 100, 900, 900)):
    return {"readable": True, "notes": [], "visuals": [], "blocks": [
        {"id": str(i), "kind": "text", "bbox": list(box) if i == 0 else [10, 10, 80, 80],
         "text": "fixture", "uncertainties": []} for i in range(count)]}


class Transport:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def __call__(self, request, timeout):
        prompt = json.loads(request.data)["input"][0]["text"]
        self.prompts.append(prompt)
        response = {"status": "completed", "output_text": json.dumps(self.answer(prompt))}
        return io.BytesIO(json.dumps(response).encode())


def test_replay_only_the_rejected_stage_of_page_41(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CONTENT_API_KEY", "synthetic-only")
    fixture = FIXTURE["oversize"]
    bad = layers(fixture["block_count"], fixture["bbox"])
    with pytest.raises(ValueError):
        validate(bad, EXTRACT)
    transport = Transport(lambda prompt: bad if prompt == "page 41" else layers(1))
    client = Gemini(tmp_path, "fixture", None, max_calls=60, delay=0, transport=transport)
    for page in range(1, 41):
        client.call("layers_extract", [], f"page {page}", EXTRACT)
    with pytest.raises(Blocked, match="invalid_model_response"):
        client.call("layers_extract", [], "page 41", EXTRACT)
    assert len(transport.prompts) == 43
    assert len({signature(read(f)["response"]) for f in tmp_path.glob("*.invalid-*.json")}) == 1
    transport.prompts.clear()
    client.ppt_retry_round = 1
    for page in range(1, 42):
        assert client.call("layers_extract", [], f"page {page}", EXTRACT)["readable"]
    assert len(transport.prompts) == 1 and transport.prompts[0].startswith("page 41")
    client.ppt_retry_round = 2
    client.call("layers_extract", [], "page 41", EXTRACT)
    assert len(transport.prompts) == 1


def test_coordinate_cached_recovery_records_original_and_uses_zero_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CONTENT_API_KEY", "synthetic-only")
    fixture = FIXTURE["coordinate"]
    answer = layers(fixture["block_count"], fixture["bbox"])
    transport = Transport(lambda _: answer)
    client = Gemini(tmp_path, "fixture", None, delay=0, transport=transport)
    with pytest.raises(Blocked, match="invalid_model_response"):
        client.call("layers_extract", [], "page 2", EXTRACT)
    client.ppt_retry_round = 1
    transport.prompts.clear()
    repaired = client.call("layers_extract", [], "page 2", EXTRACT)
    assert repaired["blocks"][0]["bbox"] == [391, 57, 610, 1000]
    cached, = [read(p) for p in tmp_path.glob("*.json") if "normalization" in read(p)]
    assert cached["normalization"] == [{"layer": "blocks", "index": 0, "before": fixture["bbox"],
                                        "after": [391, 57, 610, 1000]}]
    assert cached["original_response_sha256"] and transport.prompts == []


@pytest.mark.parametrize("box", [[391,57,610,1013],[50,990,60,1012],[-2,20,80,1008],[500,1002,800,1012]])
def test_unsafe_clamp_is_held(box):
    from video_extraction.pipeline import ppt_recovery
    value = layers(1, box)
    assert ppt_recovery.normalized_layers(value) == (value, [])


def checks(ids):
    return {"complete_scan": True, "regions": [], "checks": [
        {"id": i, "decision": "uncertain", "source_clear": False, "reason": "fixture"} for i in ids]}


def test_wrong_cached_mapping_only_regenerates_the_repair(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CONTENT_API_KEY", "synthetic-only")
    f = FIXTURE["mapping"]
    image = tmp_path / "fixture.png"
    image.write_bytes(b"synthetic")
    task = {"id": "slide-10", "source_kind": "ppt", "image": str(image)}
    result = {"final_blocks": [], "visuals": []}
    issues = [{"id": i} for i in f["expected_checks"]]
    path = tmp_path / "audit.json"
    data = {"unit_id": task["id"], "regions": [], "issues": issues}
    binding = signature({"image": digest_file(image), "data": data, "prompt": source_followup.PROMPT, "stage": "audit"})
    receipt = {"binding": binding, "answer": checks(f["first_checks"])}
    save(path, receipt)
    repair = tmp_path / "audit-issue-mapping-v1.json"
    save(repair, {"binding": signature({"original_receipt": receipt, "expected_issue_ids": f["expected_checks"],
                                       "policy": "document_issue_mapping_retry_v1"}), "answer": checks(f["repair_checks"][:-1])})
    transport = Transport(lambda _: checks(f["expected_checks"]))
    client = Gemini(tmp_path / "cache", "fixture", None, delay=0, transport=transport)
    with pytest.raises(ValueError, match="source_followup_issue_mapping"):
        source_followup.inspect(task, result, issues, tmp_path, client, "audit")
    assert transport.prompts == []
    client.ppt_retry_round = 1
    answer = source_followup.inspect(task, result, issues, tmp_path, client, "audit")
    assert answer["answer"] == checks(f["expected_checks"]) and len(transport.prompts) == 1
    assert "PPT review round 1" in transport.prompts[0]
    assert source_followup.inspect(task, result, issues, tmp_path, None, "audit", read_only=True) == answer
    assert len(transport.prompts) == 1 and read(path) == receipt


@pytest.mark.parametrize("case", ["complement", "complete", "missing", "duplicate", "overlap",
                                  "conflict", "extra", "input_changed", "repair_changed"])
def test_page_10_cached_confirm_mapping(tmp_path, case):
    fixture = FIXTURE["mapping"]
    expected = fixture["expected_checks"]
    first = checks(fixture["first_checks"])
    repair = checks(fixture["repair_checks"])
    for check in first["checks"] + repair["checks"]:
        check.update(decision="existing_supported", source_clear=True)
    image = tmp_path / "slide.png"
    image.write_bytes(b"page-10")
    task = {"id": "slide-10", "source_kind": "ppt", "image": str(image)}
    result = {"final_blocks": [], "visuals": []}
    issues = [{"id": i} for i in expected]
    binding = signature({"image": digest_file(image), "data": {"unit_id": task["id"], "regions": [], "issues": issues},
                         "prompt": source_followup.PROMPT, "stage": "confirm"})
    original = {"binding": binding, "answer": first}
    path = tmp_path / "confirm.json"
    corrected = tmp_path / "confirm-issue-mapping-v1.json"
    save(path, original)
    items = repair["checks"]
    if case == "missing":
        items.pop()
    elif case == "duplicate":
        items.append(items[-1])
    elif case == "complete":
        items.extend(first["checks"])
    elif case in {"overlap", "conflict"}:
        items[-1] = dict(first["checks"][0])
        if case == "conflict":
            items[-1]["decision"] = "uncertain"
    elif case == "extra":
        items.append({**items[-1], "id": "unexpected"})
    repair_binding = signature({"original_receipt": original, "expected_issue_ids": expected,
                                "policy": "document_issue_mapping_retry_v1"})
    save(corrected, {"binding": "unrelated" if case == "repair_changed" else repair_binding, "answer": repair})
    if case == "input_changed":
        image.write_bytes(b"different page")
    args = (task, result, issues, tmp_path)
    if case in {"complement", "complete"}:
        client = SimpleNamespace(ppt_retry_round=2, call=Mock(side_effect=AssertionError("unexpected paid request")))
        answer = source_followup.inspect(*args, client, "confirm")
        client.call.assert_not_called()
        assert sorted(c["id"] for c in answer["answer"]["checks"]) == sorted(expected)
        assert answer["mapping_repair"] == {
            "policy": "ppt_complementary_checks_v1" if case == "complement" else "document_issue_mapping_retry_v1",
            "original_sha256": digest_file(path), "repair_sha256": digest_file(corrected)}
        assert source_followup.inspect(*args, None, "confirm", read_only=True) == answer
    else:
        with pytest.raises(ValueError, match="source_followup_(issue_mapping|audit_changed|mapping_repair_changed)"):
            source_followup.inspect(*args, None, "confirm", read_only=True)


def test_code_only_ppt_chunks_keep_their_own_page():
    from lerny.team_engine import chunk_locator
    from video_extraction.pipeline import data_integration
    from video_extraction.pipeline.concept_chunking import build_corpus_from_bundles

    def code(i, page):
        return {"id": i, "source_id": "src", "source_sha256": "src", "source_file": "lecture.pptx",
                "kind": "code", "modality": "visual", "observed_text": f"print({i!r})",
                "location": {"page": page} if page else {}}

    bundles = data_integration.integrate_records([code("a", 4), code("b", 7), {**code("c", None), "unit_id": None}])
    chunks = build_corpus_from_bundles(bundles)["chunks"]
    assert len({c["id"] for c in chunks}) == 3
    assert {tuple(c["provenance"]["record_ids"]): c["page"] for c in chunks} == {
        ("a",): 4, ("b",): 7, ("c",): None}
    for c in chunks:
        if c["page"] is not None:
            assert chunk_locator({**c, "document_type": "pptx"})["slide"] == c["page"]


@pytest.mark.parametrize("code", ["DOCUMENT_VALIDATION_INCOMPLETE","DOCUMENT_MODEL_REVIEW_FAILED"])
def test_manual_retry_keeps_document_gateway_generation(code):
    job = SimpleNamespace(kind="extract", payload={"version_id":"version","_ai_generation":2}, error_code=code)
    prepare_retry(job, SimpleNamespace(get=lambda *_: SimpleNamespace(filename="lecture.PPTX")))
    assert job.payload["_ai_generation"] == 2 and job.payload["_ppt_review_round"] == 1
    prepare_retry(job, SimpleNamespace(get=lambda *_: SimpleNamespace(filename="lecture.pdf")))
    assert job.payload["_ai_generation"] == 3


@pytest.mark.parametrize("reason", ["invalid_model_response", "source_followup_audit_changed",
                                    "source_followup_mapping_repair_changed"])
def test_page_hold_allows_subsequent_page_and_only_dependent_links(tmp_path, monkeypatch, reason):
    from contextlib import nullcontext
    from video_extraction.pipeline import ppt_recovery
    units = [{"id": str(i), "source_kind": "ppt", "location": {"page": i}} for i in (1,2,3)]
    tasks = [{"id": u["id"], "unit": u, "kind": "visual"} for u in units]
    tasks.append({"id":"link", "kind":"document_links", "pages": units[:2]})
    plan = {"source_plan":{"gemini_model":"fixture"}, "tasks": tasks}
    monkeypatch.setattr(connected, "verify", lambda _: plan)
    # Exercise the real result payload hash, task binding and disk checkpoints.
    monkeypatch.setattr(connected, "revalidate_result", lambda *_:None)
    monkeypatch.setattr(connected, "lock", lambda _:nullcontext())
    monkeypatch.setattr(connected.runtime_tools, "audit", lambda *_:{"checks":[], "core_ready":True})
    monkeypatch.setattr(connected, "api_key", lambda _: "fake")
    monkeypatch.setattr(connected, "publish", lambda *_:{
        "all_tasks_processed":False, "pending":len(tasks)-len(connected.done(tmp_path,plan))})
    visited = []
    def visual(unit, plan, folder, client, context):
        visited.append(unit["id"])
        if unit["id"] == "2":
            raise ValueError(reason)
        return {"records":[]}
    monkeypatch.setattr(connected, "visual", visual)
    summary = connected.run(tmp_path, None, transport=lambda *_: pytest.fail("unexpected call"), ppt_retry_round=0)
    assert visited == ["1","2","3"] and [(h["page"], h["reason"]) for h in summary["held_pages"]] == [(2, reason)]
    visited.clear()
    connected.run(tmp_path, None, ppt_retry_round=0)
    assert visited == []
    connected.run(tmp_path, None, ppt_retry_round=1)
    assert visited == ["2"]
    other = {"id":"unexplained","kind":"code"}
    assert not ppt_recovery.classified_holds(tmp_path, {**plan,"tasks":[other]}, {}, 1)



@pytest.fixture
def checkpoint_engines(monkeypatch):
    import hashlib
    import sys
    # Hash the Linux release form when Git checked out CRLF files on Windows.
    connected.hashes()
    def linux_code_digest(path):
        return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    for name, module in list(sys.modules.items()):
        if name.startswith("video_extraction") and getattr(module,"digest_file",None) is digest_file:
            monkeypatch.setattr(module,"digest_file",linux_code_digest)
    current = connected.hashes()
    # Exact Linux module digests from the deployed 4cd519e engine.
    production = {
        **current,
        "audio_crosscheck.py": "c6566c486e99e36ac7913c1eba80a22ca239510cdefc08f6a92e3a8442464689",
        "gemini.py": "59bed6b2d4fb3682525000d52bb7afcc537418ff32050ca2081d2d9a4026b496",
        "common.py": "cfa3c20a8577e38f1c7efacfac240d478cfbf2c9bd99a84e0b0b5a74dfa63daa",
        "video_extraction.shared.common": "cfa3c20a8577e38f1c7efacfac240d478cfbf2c9bd99a84e0b0b5a74dfa63daa",
        "connected": "ae4efe152264c207b50406f53faca5e95e8e23b334338f4388d5741d8c169246",
        "video_extraction.pipeline.ppt_recovery": "42917735ab9a14f821f5066dd722a1063caed870a54fca8ba15b29cab401be4d",
        "video_extraction.pipeline.source_followup": "868121fae854762472e15a96385a23dc7228578acf7c75c3609de279391777d7",
    }
    old = {**production, **{"connected":"de46459355570f76dbd8d7f1e85e12d6ac5ea99693ca597565f3b8dff1ac8778","gemini.py":"84ebe4b9a4ecf0448787b4913e01119fc195b298b2190f04acc7e5c90c9a2c04","video_extraction.pipeline.source_followup":"54c5ed0a3a21f84c4648146ec9649cbb0919bb80795b28bbb87a46dc69c19281"}}
    del old["video_extraction.pipeline.ppt_recovery"]
    complement = {**production, **{name: current[name] for name in (
        "video_extraction.pipeline.ppt_recovery", "video_extraction.pipeline.source_followup")}}
    complement["connected"] = "5cab6da57a5aa8a25b5bdcf650eccb5b6c8cd4098df25d7aab4fc42a3bb9a4be"
    return current, {"original": old, "deployed": production, "complement": complement}


@pytest.mark.parametrize("engine", ["original", "deployed", "complement"])
def test_pinned_production_plan_retains_binding_and_source_checks(tmp_path, checkpoint_engines, engine):
    from video_extraction.pipeline import ppt_recovery
    current, versions = checkpoint_engines
    old = versions[engine]
    source = tmp_path / "source.pptx"
    source.write_bytes(b"synthetic source")
    plan = {"source_plan":{"sources":[{"kind":"ppt"}], "request":{"sources":[str(source)]}, "gemini_model":"fixture"},
            "code_hashes":old, "inputs":{str(source):digest_file(source)}}
    assert ppt_recovery.compatible(plan, current)
    assert not ppt_recovery.compatible(plan, {**current, "runner":"unknown"})
    assert not ppt_recovery.compatible({**plan,"code_hashes":{**old,"runner":"unknown"}}, current)
    output = tmp_path / ("analysis-"+signature({"engine":old,"model":"fixture","policy":"fixture"})[:20])
    save(output / "plan.json", plan)
    assert ppt_recovery.output_folder(tmp_path,tmp_path/"new",current,"fixture","fixture",source) == output
    assert connected.verify(output) == plan
    source.write_bytes(b"different")
    with pytest.raises(ValueError, match="bound_source_changed"):
        connected.verify(output)


@pytest.mark.parametrize("engine", ["original", "deployed"])
def test_resume_skips_55_saved_tasks_from_each_production_engine(tmp_path, monkeypatch, checkpoint_engines, engine):
    from contextlib import nullcontext
    from video_extraction.pipeline import ppt_recovery
    current, versions = checkpoint_engines
    source = tmp_path / "source.pptx"
    source.write_bytes(b"synthetic deck")
    units = [{"id": f"p{i}", "source_kind": "ppt", "location": {"page": i}} for i in range(1, 52)]
    tasks = [{"id": u["id"], "kind": "visual", "unit": u} for u in units]
    tasks += [{"id": f"link{i}", "kind": "document_links", "pages": units[i:i+2]} for i in range(50)]
    plan = {"tasks": tasks, "code_hashes": versions[engine], "inputs": {str(source): digest_file(source)},
            "source_plan": {"sources": [{"kind": "ppt"}], "request": {"sources": [str(source)]},
                            "gemini_model": "fixture"}}
    out = tmp_path / ("analysis-" + signature({"policy": "fixture", "engine": versions[engine], "model": "fixture"})[:20])
    save(out / "plan.json", plan)
    for task in tasks[:55]:
        result = {"records": [], "specialist": task["kind"], "evidence_files": {},
                  "binding": signature({"plan": signature(plan), "task": task})}
        result["payload_hash"] = signature(result)
        save(out / "results" / (signature(task["id"])[:24] + ".json"), result)
    assert ppt_recovery.output_folder(tmp_path, tmp_path / "new", current, "fixture", "fixture", source) == out
    # Synthetic receipts exercise plan selection, binding, and the real runnable filter.
    monkeypatch.setattr(connected, "revalidate_result", lambda *_: None)
    monkeypatch.setattr(connected, "lock", lambda _: nullcontext())
    monkeypatch.setattr(connected.runtime_tools, "audit", lambda *_: {"core_ready": True, "checks": []})
    monkeypatch.setattr(connected, "api_key", lambda _: "fixture")
    monkeypatch.setattr(connected, "publish", lambda *_: {"pending": 46, "all_tasks_processed": False})
    calls = []
    def record(task, results, target, client):
        calls.append(task["id"])
        return {"records": []}
    monkeypatch.setattr(connected.document_links, "run", record)
    monkeypatch.setattr(connected, "visual", lambda *_: pytest.fail("completed page scheduled"))
    connected.run(out, None, ppt_retry_round=1, review_concurrency=4,
                  transport=lambda *_: pytest.fail("unexpected Gemini request"))
    assert sorted(calls) == sorted(t["id"] for t in tasks[55:])
