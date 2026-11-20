"""Site upload -> real common calculation gates -> isolated DB, with fake model replies.

No live API, production data, model downloads, or rendering service. Native PPT
parsers and saved-evidence replay are real; external page rendering is substituted.
"""
import copy
import io
import json
import os
import time
from datetime import UTC, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pptx import Presentation
from sqlalchemy import select

from lerny import document_materials as documents, gemini_provider, media_progress, worker
from lerny.auth import COOKIE
from lerny.gemini_quota import ProviderDeferred
from lerny.gemini_runtime import needs_remote
from lerny.models import Chunk, Job, Material, MaterialVersion, now
from video_extraction.pipeline import connected
from video_extraction.shared.common import digest_file, save
from video_extraction.tests.test_correction_gate import block, result
from test_gemini_integration import configured, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401

TEXT = "Stack follows LIFO"


def source(suffix):
    stream = io.BytesIO()
    if suffix == ".pptx":
        ppt = Presentation()
        slide = ppt.slides.add_slide(ppt.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, ppt.slide_width, ppt.slide_height).text = TEXT
        ppt.save(stream)
    else:
        pdf = PdfWriter()
        pdf.add_blank_page(width=300, height=200)
        pdf.write(stream)
    return stream.getvalue()


@pytest.fixture
def site(integration, monkeypatch):
    client, session, tokens = integration
    monkeypatch.setattr(documents, "engine", lambda: session.bind)
    monkeypatch.setattr(media_progress, "engine", lambda: session.bind)
    monkeypatch.setattr(worker, "heartbeat", lambda *_: None)
    if os.name == "nt" and not str(documents.settings().runtime_root).startswith("\\\\?\\"):
        config = documents.settings()
        monkeypatch.setattr(config, "runtime_root", Path("\\\\?\\" + str(config.runtime_root.resolve())))
    original_extract = worker.extract_job
    def traced_extract(*args):
        try:
            return original_extract(*args)
        except Exception:
            import traceback
            traceback.print_exc()
            raise
    monkeypatch.setattr(worker, "extract_job", traced_extract)
    monkeypatch.setenv("LERNY_GEMINI_CONTENT_API_KEY", "synthetic-test-key")
    # native_reader is an isolated subprocess and must import this checkout.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    return client, session, tokens


@pytest.fixture
def synthetic_engine(monkeypatch):
    state = SimpleNamespace(calls=[], unsafe=False, failure=None, candidate_calls=0, text=TEXT, boundary_texts={})
    fallback = gemini_provider.request

    def render(path, folder, config, kind=None):
        folder.mkdir(parents=True, exist_ok=True)
        image = folder / "page.png"
        im = Image.new("RGB", (300, 200), "white")
        ImageDraw.Draw(im).text((40, 60), state.text[:40], fill="black")
        im.save(image)
        kind = "ppt" if path.suffix == ".pptx" else "pdf"
        return {"kind": kind, "source_file": str(path), "source_sha256": digest_file(path)}, [{
            "image": str(image), "location": {"page": 1}, "native_text": state.text,
            "modality": "visual", "dimensions": [300, 200], "time_seconds": 1,
            "pdf_inventory": {"route": "scan_or_graphics_render", "words": []}}]

    def candidate(frame, *_args, **_kwargs):
        state.candidate_calls += 1
        before = block("x[0]" if state.unsafe else state.text, "code" if state.unsafe else "text")
        after = block("x[o]", "code") if state.unsafe else copy.deepcopy(before)
        value = result(before, after)
        value.update(signature="synthetic", image_sha256=digest_file(frame["path"]), audit={})
        return value

    def provider(path, payload, parse):
        if path != "interactions" or not isinstance(payload.get("input"), list):
            return fallback(path, payload, parse)
        assert path == "interactions" and payload["store"] is False
        prompt = payload["input"][0]["text"]
        data = json.loads(prompt.split("DATA:\n", 1)[1])
        state.calls.append(payload)
        if state.failure:
            raise state.failure
        if "native_inventory" in data:
            ids = [r["id"] for r in data["regions"]]
            value = {"complete": True, "reading_order": ids,
                     "checks": [{"id": i, "source_supported": True, "structure_supported": True,
                                 "order_clear": True, "reason": "synthetic source"} for i in ids],
                     "relations": [], "missing": [], "cross_page_uncertain": []}
        elif "issues" in data:
            value = {"complete_scan": True, "regions": [], "checks": [
                {"id": i["id"], "decision": "uncertain", "source_clear": False,
                 "reason": "unresolved synthetic evidence"} for i in data["issues"]]}
        elif "target_bbox" in data:
            # Explicit synthetic source rechecks keep the original complete region.
            # Unknown targets fail the fixture instead of silently approving them.
            value = {"target_id": data["target_id"], "text": state.boundary_texts[data["target_id"]],
                     "same_target": True, "all_target_visible": True, "no_neighbor_content": True,
                     "source_clear": True, "geometry_supported": True,
                     "original_boundary_cuts_target": False, "uncertainties": []}
        elif "record_id" in data:
            # A failed calculation gate must remain held even if a model considers it low-impact.
            value = {"impact": "unknown", "reason": "synthetic unresolved code"}
        else:
            raise AssertionError(f"Unexpected model request keys: {sorted(data)}")
        return parse({"status": "completed", "output_text": json.dumps(value)})

    monkeypatch.setattr(connected.base.adapters, "prepare_source", render)
    monkeypatch.setattr(connected.runtime_tools, "audit", lambda *_: {
        "checks": [{"tool": "PaddleOCR", "required": False, "ok": False}], "core_ready": True})
    monkeypatch.setattr(connected.base.visual, "process_frame_layers", candidate)
    monkeypatch.setattr(gemini_provider, "request", provider)
    return state


def upload(site, suffix, visibility="public"):
    client, session, _ = site
    response = client.post("/api/v1/courses/course/materials",
        data={"kind": "lecture", "week": "3", "visibility": visibility},
        files={"file": ("source" + suffix, source(suffix), "application/octet-stream")})
    assert response.status_code == 201, response.text
    data = response.json()
    session.expire_all()
    return session.get(Job, data["processing_job_id"]), session.get(MaterialVersion, data["version_id"])


@pytest.mark.parametrize("suffix", [".pptx", ".pdf"])
def test_site_upload_runs_common_gates_and_reuses_completed_results(site, synthetic_engine, suffix):
    client, session, tokens = site
    before = [(c.id, c.content) for c in session.scalars(select(Chunk))]
    job, version = upload(site, suffix)
    assert needs_remote(session, job)
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded", job.error_code
    assert version.status == "extracted" and TEXT in version.extracted_text
    assert version.extraction_report["native_evidence"]["mandatory_calculation_gate"]
    chunks = list(session.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    assert chunks and all(c.locator["slide" if suffix == ".pptx" else "page"] == 1 for c in chunks)
    assert all(session.get(Chunk, i).content == text for i, text in before)
    assert session.scalar(select(Job).where(Job.kind == "embed", Job.payload["version_id"].as_string() == version.id))
    assert synthetic_engine.calls
    cache = list(documents.settings().runtime_root.glob("document-materials/*/analysis-*/gemini-cache/*.json"))
    assert cache
    hashes = {p: digest_file(p) for p in cache}
    call_count = len(synthetic_engine.calls)
    # Same extraction is retried explicitly: completed specialist results and cache survive.
    job.status = "queued"
    session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded" and len(synthetic_engine.calls) == call_count
    assert all(digest_file(p) == h for p, h in hashes.items())
    assert synthetic_engine.candidate_calls == 1
    review_url = f"/api/v1/materials/{version.material_id}/extraction-review"
    assert client.get(review_url).status_code == 200
    client.cookies.set(COOKIE, tokens["student"][0])
    assert client.get(review_url).status_code in {403, 404}


def test_model_approval_cannot_override_code_calculation_hold(site, synthetic_engine):
    synthetic_engine.unsafe = True
    _, session, _ = site
    job, version = upload(site, ".pdf")
    worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded", job.error_code
    assert version.status == "needs_review" and not version.extracted_text
    assert not session.scalar(select(Chunk).where(Chunk.version_id == version.id))
    assert not session.scalar(select(Job).where(Job.kind == "embed"))
    held = version.extraction_report["review_queue"]
    assert held and all(row["source_locator"] == "문서 1쪽" for row in held)
    assert any("x[0]" in row.get("observed_text", "") for row in held)
    assert all(not row["eligible_for_chunking"] for row in held)


def test_quota_wait_retains_progress_then_resumes(site, synthetic_engine):
    _, session, _ = site
    job, version = upload(site, ".pdf")
    synthetic_engine.failure = ProviderDeferred("GEMINI_DAILY_WAIT", time.time() + 3600)
    worker.run_once(job.id)
    session.expire_all()
    assert job.status == "queued" and job.error_code == "GEMINI_DAILY_WAIT"
    assert job.attempt == 0 and job.lease_until.replace(tzinfo=UTC) > now()
    assert media_progress.public_progress(job)["stage"] == "document_review"
    assert not version.extracted_text and not session.scalar(select(Job).where(Job.kind == "embed"))
    synthetic_engine.failure = None
    job.lease_until = now() - timedelta(seconds=1)
    session.commit()
    worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded" and TEXT in version.extracted_text


def test_document_slice_budget_reuses_prior_responses(site, synthetic_engine, configured, monkeypatch):
    _, session, _ = site
    monkeypatch.setattr(configured, "gemini_max_calls_per_job", 1)
    job, version = upload(site, ".pdf")
    for _ in range(5):
        worker.run_once(job.id)
        session.expire_all()
        if job.status == "succeeded":
            break
        assert job.status == "queued" and job.error_code == "DOCUMENT_CHECKPOINT_PENDING"
        assert media_progress.public_progress(job)["stage"] == "document_review"
        job.lease_until = now() - timedelta(seconds=1)
        session.commit()
    assert job.status == "succeeded" and TEXT in version.extracted_text
    # Structure review, audit, confirm: cached earlier calls are not billed/repeated.
    assert len(synthetic_engine.calls) == 3


def test_pause_cloud_filter_and_cancellation_prevent_calls(site, synthetic_engine, configured, monkeypatch):
    _, session, _ = site
    job, version = upload(site, ".pdf")
    monkeypatch.setattr(configured, "gemini_calls_enabled", False)
    worker.run_once(job.id)
    session.expire_all()
    assert job.status == "waiting_ai" and not synthetic_engine.calls
    monkeypatch.setattr(configured, "gemini_calls_enabled", True)
    monkeypatch.setattr(configured, "deployment", "cloud")
    assert not worker.run_once(job.id)
    monkeypatch.setattr(configured, "deployment", "local")
    job.status, job.lease_token, job.lease_until = "running", "lease", now() + timedelta(seconds=60)
    session.commit()
    documents.check_source(job.id, "lease", version.id, version.sha256)
    material = session.get(Material, version.material_id)
    material.visibility = "private"
    session.commit()
    with pytest.raises(ValueError, match="DOCUMENT_SOURCE_CHANGED"):
        documents.check_source(job.id, "lease", version.id, version.sha256)
    with pytest.raises(ValueError, match="DOCUMENT_JOB_CANCELLED"):
        documents.check_source(job.id, "stale", version.id, version.sha256)
    assert not synthetic_engine.calls


@pytest.mark.parametrize("suffix,visibility,manual", [
    (".mp4", "public", False), (".pptx", "private", False),
    (".pdf", "private", False), (".pptx", "public", True), (".docx", "public", False)])
def test_other_sources_keep_existing_local_route(site, monkeypatch, suffix, visibility, manual):
    _, session, _ = site
    version = session.get(MaterialVersion, "version")
    material = session.get(Material, "material")
    version.filename = "source" + suffix
    material.visibility = visibility
    job = Job(kind="extract", owner_id="teacher", course_id="course",
              payload={"version_id": version.id, "manual_text": manual})
    assert not documents.eligible(job, version, material) and not needs_remote(session, job)
    monkeypatch.setattr(documents, "extract_job", lambda *_: pytest.fail("Unexpected document model route"))
    import lerny.media_materials as media
    import lerny.team_ingestion as native
    monkeypatch.setattr(media, "media_extract_job", lambda *_: {"route": "video"})
    monkeypatch.setattr(native, "native_extract_job", lambda *_: {"route": "native"})
    monkeypatch.setattr(worker, "extract", lambda *_: [])
    worker.extract_job(session, job)


def test_tampered_source_and_receipt_never_replace_old_chunks(site, synthetic_engine):
    _, session, _ = site
    job, version = upload(site, ".pdf")
    worker.run_once(job.id)
    session.expire_all()
    before = [(c.id, c.content) for c in session.scalars(select(Chunk))]
    root = documents.settings().runtime_root
    evidence = next(root.glob("document-materials/*/analysis-*/work/*/visual-base.json"))
    evidence.write_text("{}", encoding="utf-8")
    calls = len(synthetic_engine.calls)
    job.status = "queued"
    session.commit()
    worker.run_once(job.id)
    session.expire_all()
    assert job.status == "failed" and len(synthetic_engine.calls) == calls
    assert [(c.id, c.content) for c in session.scalars(select(Chunk))] == before
    cached_source = next(root.glob("document-materials/*/source.pdf"))
    cached_source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        documents.process(cached_source, cached_source.parent, version.sha256, lambda: None, lambda *_: None)


def test_low_impact_and_dependent_relations_are_not_rag_evidence(tmp_path, monkeypatch):
    # The legacy publisher may offer low-impact warnings. Site selection is stricter.
    unit = {"id": "unit", "source_id": "a" * 64, "source_file": "source.pdf", "source_kind": "pdf",
            "location": {"page": 1}, "modality": "visual", "time_seconds": 1}
    good = connected.base.base_record(unit, "good", "text", "text", TEXT)
    good.update(eligible_for_chunking=True, judgment="source_rechecked")
    warning = {**good, "id": "warn", "observed_text": "UNAPPROVED", "low_impact_warning": True}
    relation = {**good, "id": "relation", "kind": "relation", "related_record_ids": ["warn"]}
    revision = tmp_path / "revision"
    revision.mkdir()
    files = {}
    for name, rows in [("usable-records.jsonl", [good, warning, relation]), ("review-required.jsonl", [])]:
        path = revision / name
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        files[name] = digest_file(path)
    save(revision / "manifest.json", {"files": files})
    save(tmp_path / "latest.json", {"manifest": str(revision / "manifest.json")})
    monkeypatch.setattr(connected, "publish", lambda *_: None)
    got = documents.selection(tmp_path, {"source_plan": {"units": [unit]}}, "a" * 64, ".pdf", {})
    assert {row["id"] for row in got["held"]} == {"warn", "relation"}
    assert got["chunks"] and all("UNAPPROVED" not in c["text"] for c in got["chunks"])


def test_render_failure_retries_in_new_revision_without_deleting_evidence(tmp_path, configured, monkeypatch):
    path = tmp_path / "source.pdf"
    path.write_bytes(source(".pdf"))
    folders = []
    def prepare(folder, **_):
        folders.append(folder)
        plan = {"source_plan": {"source_issues": [{"reason": "missing_local_tool:pdftoppm"}]}}
        save(folder / "plan.json", plan)
        return plan
    monkeypatch.setattr(connected, "prepare", prepare)
    for _ in range(2):
        with pytest.raises(ValueError, match="DOCUMENT_TOOLS_NOT_READY"):
            documents.process(path, tmp_path, digest_file(path), lambda: None, lambda *_: None)
    assert folders[0] != folders[1]
    assert all((folder / "plan.json").is_file() for folder in folders)
