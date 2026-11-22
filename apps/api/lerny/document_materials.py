"""Site PPTX/PDF uploads -> existing Gemini + mandatory calculation gates.

Only new/explicitly queued public source versions enter this adapter. It never
migrates completed extractions, changes billing/model settings, or processes MP4.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import Job, Material, MaterialVersion, now
from video_extraction.shared.common import digest_file, read, save, signature

POLICY = "site-document-gemini-gates-v1"
FORMATS = {".pptx", ".pdf"}


class DocumentStopped(RuntimeError):
    """Cancellation must escape specialist ValueError-to-held handling."""


def eligible(job, version, material):
    from lerny.material_policy import student_source
    if not version or not material or material.deleted or job.payload.get("manual_text") or not student_source(material):
        return False
    suffix = Path(version.filename).suffix.lower()
    config = settings()
    if suffix == ".pptx" and config.instructor_reviews_week(material.course_id, material.week):
        return config.paid_upload(material.course_id, material.week, version.created_at)
    return suffix in FORMATS


def check_source(job_id, token, version_id, source_sha):
    with Session(engine()) as session:
        job = session.scalar(select(Job).where(Job.id == job_id, Job.status == "running",
                             Job.lease_token == token, Job.lease_until > now()))
        if not job:
            raise ValueError("DOCUMENT_JOB_CANCELLED")
        version = session.get(MaterialVersion, job.payload.get("version_id"))
        material = session.get(Material, version.material_id) if version else None
        if not version or version.id != version_id or version.sha256 != source_sha or not eligible(job, version, material):
            raise ValueError("DOCUMENT_SOURCE_CHANGED")


def configure_tools():
    # Same installed tools as handout viewing; no downloads or package installation.
    poppler = os.environ.get("LERNY_INGESTION_POPPLER_BIN")
    if poppler and Path(poppler).is_dir() and poppler not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = poppler + os.pathsep + os.environ.get("PATH", "")


def validate_source(path):
    if path.suffix == ".pdf":
        from pypdf import PdfReader
        pdf = PdfReader(path)
        if pdf.is_encrypted or not 0 < len(pdf.pages) <= 500:
            raise ValueError("PDF_LIMIT_OR_ENCRYPTED")
    else:
        from pptx import Presentation
        if not 0 < len(Presentation(path).slides) <= 300:
            raise ValueError("SLIDE_LIMIT")


def selection(output, plan, source_sha, suffix, summary):
    """Revalidate cached specialist receipts before selecting any text for the DB."""
    from video_extraction.pipeline import connected, data_integration
    from video_extraction.pipeline.concept_chunking import build_corpus_from_bundles
    connected.publish(output, plan)
    latest = read(output / "latest.json")
    manifest = Path(latest["manifest"])
    revision = manifest.parent
    if not manifest.resolve().is_relative_to(output.resolve()):
        raise ValueError("DOCUMENT_RECEIPT_INVALID")
    for name, digest in read(manifest)["files"].items():
        path = revision / name
        if not path.resolve().is_relative_to(revision.resolve()) or digest_file(path) != digest:
            raise ValueError("DOCUMENT_RECEIPT_INVALID")
    def rows(name):
        return [json.loads(line) for line in (revision / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = rows("usable-records.jsonl")
    held = rows("review-required.jsonl")
    clean = []
    for row in selected:
        if row.get("source_id", row.get("source_sha256")) != source_sha:
            raise ValueError("SOURCE_CHANGED")
        if (not row.get("eligible_for_chunking") or row.get("low_impact_warning")
                or row.get("judgment") == "accepted_with_low_impact_warning"
                or row.get("approved_for_rag") is False):
            held.append({**row, "eligible_for_chunking": False, "status": "held",
                         "reasons": [*row.get("reasons", []), "administrator_review_required"]})
        else:
            clean.append(row)
    while True:
        ids = {row["id"] for row in clean}
        dangling = [row for row in clean if set(row.get("related_record_ids", [])) - ids]
        if not dangling:
            break
        held.extend({**row, "eligible_for_chunking": False, "status": "held",
                     "reasons": [*row.get("reasons", []), "unselected_relation_target"]} for row in dangling)
        clean = [row for row in clean if row not in dangling]
    bundles = data_integration.integrate_records(clean, units=plan["source_plan"]["units"])
    chunks = build_corpus_from_bundles(bundles, limit=1800)["chunks"]
    for chunk in chunks:
        if (chunk.get("source_sha256") != source_sha or not chunk.get("eligible_for_chunking")
                or not chunk["text"].strip() or len(chunk["text"]) > 1800):
            raise ValueError("DOCUMENT_SELECTION_INVALID")
        chunk.update(document_type=suffix.lstrip("."), source_locator=f"문서 {chunk.get('page')}쪽",
                     slide_number=chunk.get("page"), quality=POLICY)
    for marker in summary.get("held_pages", []):
        page = marker["page"]
        held.append({"id": f"{source_sha}:page-review:{page}", "kind": "coverage_issue",
                     "location": {"page": page}, "reasons": [marker["reason"]], "status": "held",
                     "source_context": ("원본 쪽의 검증 항목 ID가 일치하지 않습니다."
                                        if marker["reason"] == "source_followup_issue_mapping"
                                        else "이 쪽의 모델 응답이 검증 형식을 충족하지 않았습니다."),
                     "eligible_for_chunking": False})
    for row in held:
        page = row.get("location", {}).get("page")
        row["source_locator"] = f"문서 {page}쪽" if page else "문서"
    return {"chunks": chunks, "held": held, "evidence": {
        "pipeline": POLICY, "model": plan["source_plan"].get("gemini_model", settings().gemini_answer_model),
        "source_sha256": source_sha, "selection_manifest_sha256": digest_file(manifest),
        "mandatory_calculation_gate": True, "summary": summary,
        "accuracy_pct": None, "scope": "model_source_review_and_calculation_gates_not_measured_accuracy"}}


def process(path, folder, source_sha, check, report, ppt_retry_round=0):
    from lerny.gemini_provider import media_call_budget
    from lerny.gemini_quota import ProviderDeferred, verification
    from lerny.media_materials import MediaStopped, service_transport
    from video_extraction.pipeline import connected
    from video_extraction.shared.gemini import Blocked
    from video_extraction.shared.progress import reporting
    config = settings()
    model = config.gemini_answer_model
    if config.ai_provider != "gemini":
        raise ValueError("DOCUMENT_GEMINI_REQUIRED")
    if digest_file(path) != source_sha:
        raise ValueError("SOURCE_CHANGED")
    validate_source(path)
    configure_tools()
    # Source-bound evidence nests several directories. Windows dev runtimes may
    # not enable LongPathsEnabled; use the native extended path for new outputs.
    if os.name == "nt" and not str(folder).startswith("\\\\?\\"):
        folder = Path("\\\\?\\" + str(folder.resolve()))
    # Keep old policy outputs intact; the service gateway still reuses matching responses.
    output = folder / ("analysis-" + signature({"policy": POLICY, "engine": connected.hashes(),
                                               "model": model})[:20])
    if path.suffix.lower() == ".pptx":
        from video_extraction.pipeline import ppt_recovery
        output = ppt_recovery.output_folder(folder, output, connected.hashes(), model, POLICY, path)
    base_output = output
    attempt = 0
    # A failed render is frozen in the common preparation plan. Preserve that
    # evidence and prepare a new revision after tools/the renderer are repaired.
    while (output / "plan.json").exists() and read(output / "plan.json")["source_plan"].get("source_issues"):
        attempt += 1
        output = base_output.with_name(base_output.name + f"-prepare-{attempt}")
    def active():
        try:
            check()
        except ValueError as exc:
            raise DocumentStopped(str(exc)) from None
    def progress(stage, completed=0, total=None):
        # connected.run finalizes its checkpoint even when interrupted. Only the
        # successful return below means all document tasks have been processed.
        if stage in {"finalize", "alignment"}:
            return
        active()
        label = {"video_review": "document_review", "source_check": "document_review"}.get(stage, "document_preparing")
        report(label, completed, total)
    def transport(request, timeout=150):
        active()
        if path.suffix.lower() == ".pptx":
            with verification():
                return service_transport(request, timeout, expected_model=model)
        return service_transport(request, timeout)
    try:
        with reporting(progress), media_call_budget():
            progress("preparing")
            plan = connected.prepare(output, inputs=[path], model=model,
                                     native_python=sys.executable, code_python=sys.executable,
                                     alignment_allow_download=False,
                                     ocr_models=os.environ.get("LERNY_INGESTION_OCR_MODELS"),
                                     ocr_python=os.environ.get("LERNY_INGESTION_OCR_PYTHON"))
            issues = plan["source_plan"].get("source_issues", [])
            if issues:
                if any(str(issue.get("reason", "")).startswith("missing_local_tool:") for issue in issues):
                    raise ValueError("DOCUMENT_TOOLS_NOT_READY")
                raise ValueError("DOCUMENT_RENDER_FAILED")
            active()
            summary = connected.run(output, None, maximum=config.gemini_max_calls_per_job,
                                    delay=0, transport=transport,
                                    **({"ppt_retry_round": ppt_retry_round} if path.suffix.lower() == ".pptx" else {}))
            if not summary["all_tasks_processed"] and not summary.get("held_pages"):
                raise ValueError("DOCUMENT_VALIDATION_INCOMPLETE")
            active()
            if digest_file(path) != source_sha:
                raise ValueError("SOURCE_CHANGED")
            report("document_finalize", summary["completed"], summary["tasks"])
            with connected.lock(output):
                result = selection(output, plan, source_sha, path.suffix, summary)
            if path.suffix.lower() == ".pptx":
                from lerny.ppt_source_index import supplement
                from video_extraction.shared.gemini import Gemini
                supplement(path, plan, result, output / "source-regions",
                           Gemini(output / "gemini-cache", model, None,
                                  max_calls=config.gemini_max_calls_per_job, delay=0, transport=transport), active)
                active()
            save(output / "site-selection.json", result)
            return result
    except DocumentStopped as exc:
        raise ValueError(str(exc)) from None
    except MediaStopped as exc:
        if exc.retry_at:
            raise ProviderDeferred(str(exc), exc.retry_at) from None
        code = {"MEDIA_JOB_CANCELLED": "DOCUMENT_JOB_CANCELLED",
                "MEDIA_PROCESSING_FAILED": "DOCUMENT_MODEL_REVIEW_FAILED"}.get(str(exc), str(exc))
        raise ValueError(code) from None
    except Blocked as exc:
        if str(exc) in {"request_budget_exhausted", "total_request_budget_exhausted"}:
            raise ProviderDeferred("DOCUMENT_CHECKPOINT_PENDING", time.time() + 5) from None
        raise ValueError("DOCUMENT_MODEL_REVIEW_FAILED") from None
    except ValueError as exc:
        if str(exc).startswith(("missing_local_tool:", "실행 도구 점검 실패:")):
            raise ValueError("DOCUMENT_TOOLS_NOT_READY") from None
        if str(exc).startswith(("soffice_", "pdfinfo_", "pdftoppm_", "pdftotext_", "ppt_render_")):
            raise ValueError("DOCUMENT_RENDER_FAILED") from None
        raise


def extract_job(session, job, version, material):
    from lerny.media_progress import reporter
    from lerny.storage import source_file
    from lerny.team_ingestion import publish_extraction
    config = settings()
    if config.deployment == "cloud" and not config.dedicated_worker:
        raise ValueError("GEMINI_DEDICATED_WORKER_REQUIRED")
    if not eligible(job, version, material):
        raise ValueError("DOCUMENT_SOURCE_CHANGED")
    folder = config.runtime_root / "document-materials" / signature({"version": version.id, "sha256": version.sha256})
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("source" + Path(version.filename).suffix.lower())
    check = lambda: check_source(job.id, job.lease_token, version.id, version.sha256)
    check()
    if not path.exists():
        temporary = path.with_name(path.name + "." + job.lease_token + ".tmp")
        try:
            with source_file(version) as source:
                shutil.copyfile(source, temporary)
            if digest_file(temporary) != version.sha256:
                raise ValueError("SOURCE_CHANGED")
            check()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    check()
    retry_round = job.payload.get("_ppt_review_round", 0)
    result = process(path, folder, version.sha256, check, reporter(job.id, job.lease_token, version.id),
                     **({"ppt_retry_round": retry_round} if retry_round else {}))
    check()
    return publish_extraction(session, job, version, material, {"source_sha256": version.sha256},
                              result["chunks"], result["held"], result["evidence"])
