"""Versioned MP4 ingestion through the team's existing gated media dispatcher."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import Job, Material, MaterialVersion, now


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class MediaStopped(Exception):
    def __init__(self, code, retry_at=None):
        super().__init__(code)
        self.retry_at = retry_at


def current_source(job_id, token):
    with Session(engine()) as db:
        job = db.get(Job, job_id)
        if not job or job.status != "running" or job.lease_token != token or not job.lease_until or job.lease_until <= now():
            raise MediaStopped("MEDIA_JOB_CANCELLED")
        version = db.get(MaterialVersion, job.payload["version_id"])
        material = db.get(Material, version.material_id) if version else None
        if not material or material.deleted:
            raise MediaStopped("SOURCE_REVOKED")
        return job, version


def service_transport(request, timeout=150, *, expected_model=None):
    """Use the existing cache, pause controls and shared quota for every model request."""
    from lerny.gemini_provider import request as generate
    if request.full_url != "https://generativelanguage.googleapis.com/v1beta/interactions":
        raise MediaStopped("UNSUPPORTED_MODEL_PROVIDER")
    payload = json.loads(request.data)
    if payload.get("model") != (expected_model or settings().gemini_answer_model) or payload.get("store") is not False:
        raise MediaStopped("MEDIA_MODEL_CONFIG_MISMATCH")
    try:
        result = generate("interactions", payload, lambda raw: raw)
    except ValueError as exc:
        # The specialist treats ValueError as a held item. Quota/cancel must stop the run.
        code = str(exc) if re.fullmatch(r"[A-Z_]+", str(exc)) else "MEDIA_PROCESSING_FAILED"
        raise MediaStopped(code, getattr(exc, "retry_at", None)) from None
    return io.BytesIO(json.dumps(result).encode())


def selected_chunks(bundles, expected_hash):
    from video_extraction.pipeline.concept_chunking import build_corpus_from_bundles
    for bundle in bundles:
        if bundle.get("source_sha256") != expected_hash:
            raise ValueError("SOURCE_CHANGED")
        if bundle.get("provenance", {}).get("has_low_impact_warnings"):
            raise ValueError("UNAPPROVED_SOURCE_WARNING")
    corpus = build_corpus_from_bundles(bundles, limit=1800)
    chunks = corpus["chunks"]
    if any(not c.get("eligible_for_chunking") or len(c["text"]) > 1800 for c in chunks):
        raise ValueError("MEDIA_CHUNK_REVIEW_REQUIRED")
    for chunk in chunks:
        chunk["document_type"] = "mp4"
        interval = chunk.get("time_interval") or {}
        if interval:
            chunk["source_locator"] = "영상 구간 " + json.dumps(interval, ensure_ascii=False)
    return chunks


def process_media(path, output, job_id, token):
    from video_extraction.shared.progress import reporting
    from lerny.media_progress import reporter
    job, version = current_source(job_id, token)
    with reporting(reporter(job_id, token, version.id)):
        return _process_media(path, output, job_id, token)


def _process_media(path, output, job_id, token):
    from lerny.local_media import process
    from lerny.media_progress import reporter
    from lerny.media_references import snapshot, verify
    job, version = current_source(job_id, token)
    references = snapshot(version.id, output.parent/'ppt-references')
    def check():
        current_source(job_id, token)
        verify(references, version.id)
    return process(path, output.parent, version.sha256, check,
                   reporter(job_id, token, version.id), references=references)


def run_media(version, job):
    from lerny.gemini_quota import ProviderDeferred
    from lerny.storage import source_file
    if settings().deployment == "cloud" and not settings().dedicated_worker:
        raise ValueError("GEMINI_DEDICATED_WORKER_REQUIRED")
    # Stable paths preserve source-bound checkpoints and avoid paying for repeats.
    identity = hashlib.sha256((version.id + ":" + str(job.payload.get("_ai_generation", 0))).encode()).hexdigest()
    folder = settings().runtime_root / "media-materials" / identity
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "source.mp4"
    if not path.exists():
        with source_file(version) as source:
            shutil.copyfile(source, path)
    if file_digest(path) != version.sha256:
        raise ValueError("SOURCE_CHANGED")
    outcome = folder / "outcome.json"
    outcome.unlink(missing_ok=True)
    command = [sys.executable, "-m", "lerny.media_materials", str(path), str(folder / "analysis"), job.id, job.lease_token]
    with (folder / "processing.log").open("ab") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=os.name != "nt",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        started = time.monotonic()
        try:
            while process.poll() is None:
                current_source(job.id, job.lease_token)
                if time.monotonic() - started > 4 * 3600:
                    raise ValueError("MEDIA_TIMEOUT")
                time.sleep(0.5)
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                                   timeout=30, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
    result = json.loads(outcome.read_text()) if outcome.exists() else {"error": "MEDIA_PROCESSING_FAILED"}
    if result.get("error"):
        if result.get("retry_at"):
            raise ProviderDeferred(result["error"], result["retry_at"])
        raise ValueError(result["error"])
    if process.returncode:
        raise ValueError("MEDIA_PROCESSING_FAILED")
    return json.loads((folder / "selected.json").read_text(encoding="utf-8"))


def media_extract_job(session, job, version, material):
    from lerny.team_ingestion import publish_extraction
    result = run_media(version, job)
    return publish_extraction(session, job, version, material,
                              {"source_sha256": result["source_sha256"]}, result["chunks"],
                              result["held"], result["evidence"])


if __name__ == "__main__":
    path, output = Path(sys.argv[1]), Path(sys.argv[2])
    from lerny.gemini_provider import save_json
    try:
        process_media(path, output, sys.argv[3], sys.argv[4])
        save_json(output.parent / "outcome.json", {"ok": True})
    except Exception as exc:
        code = str(exc) if re.fullmatch(r"[A-Z_]+", str(exc)) else "MEDIA_PROCESSING_FAILED"
        if str(exc) in {"request_budget_exhausted", "total_request_budget_exhausted"}:
            code = "GEMINI_CALL_BUDGET_EXCEEDED"
        save_json(output.parent / "outcome.json", {"error": code, "retry_at": getattr(exc, "retry_at", None)})
        raise SystemExit(1)
