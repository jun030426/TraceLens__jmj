"""Gemini selection and paused jobs. These operations never contact a model."""

from sqlalchemy import select

from lerny.config import settings
from lerny.models import AuditEvent, Job, Material, MaterialVersion

PAUSE_REASONS = ("GEMINI_CALLS_DISABLED", "GEMINI_KEY_REQUIRED")


def pause_reason(purpose="all"):
    config = settings()
    if not config.gemini_calls_enabled:
        return "GEMINI_CALLS_DISABLED"
    if not config.gemini_keys_ready(purpose):
        return "GEMINI_KEY_REQUIRED"
    return None


def status():
    reason = pause_reason()
    return {
        "provider": "gemini",
        "status": "gemini_paused"
        if reason == "GEMINI_CALLS_DISABLED"
        else "gemini_not_configured"
        if reason
        else "gemini",
        "reason": reason,
        "calls_enabled": settings().gemini_calls_enabled,
        "key_configured": settings().gemini_keys_ready(),
        "embedding_key_configured": settings().gemini_keys_ready("embedding"),
        "content_key_configured": settings().gemini_keys_ready("content"),
        "live_verified": False,
        "message": (
            "Gemini를 사용하도록 설정했어요. 실제 API 호출은 일시 중지 중이며, 자료 저장과 텍스트 확인은 계속할 수 있어요."
            if reason == "GEMINI_CALLS_DISABLED"
            else "Gemini API 키 설정이 필요해요. 자료 저장과 텍스트 확인은 계속할 수 있어요."
            if reason
            else "Gemini 연결 설정이 준비됐어요. 실제 연결은 아직 검증하지 않았어요."
        ),
    }


def needs_remote(session, job):
    if job.kind == "material_preview":
        return False
    if job.kind == "lecture_slides" and (job.result or {}).get("plan"):
        return False  # Reuse the reviewed plan; Google export needs no model call.
    if job.kind == "extract":
        from lerny.document_materials import eligible
        version = session.get(MaterialVersion, job.payload.get("version_id"))
        material = session.get(Material, version.material_id) if version else None
        return eligible(job, version, material)  # MP4 and private/manual sources remain local.
    if job.kind == "practice_grade":
        return False
    if job.kind == "embed":
        version = session.get(MaterialVersion, job.payload["version_id"])
        material = session.get(Material, version.material_id) if version else None
        # Extraction/indexing stays local. Selected answer excerpts may be sent only
        # by a later validation/grading job, which still honors the global pause.
        if material and (material.visibility != "public" or material.internal_use != "none" or material.kind == "answer"):
            return False
    return True


def hold(session, job, reason):
    job.status, job.error_code = "waiting_ai", reason
    job.lease_token, job.lease_until = None, None
    if job.kind in {"extract", "embed"}:
        version = session.get(MaterialVersion, job.payload["version_id"])
        version.status, version.error_code = ("extracted" if job.kind == "embed" else "queued"), reason


def migrate_extracted_materials(session):
    """Explicit one-time transition. Preserve completed/legacy job history and all source data."""
    config = settings()
    if (
        config.deployment != "local"
        or config.ai_provider != "gemini"
        or config.gemini_calls_enabled
    ):
        raise ValueError("GEMINI_PAUSED_LOCAL_REQUIRED")
    migrated = []
    for material in session.scalars(
        select(Material).where(Material.deleted.is_(False)).with_for_update()
    ):
        version = session.scalar(
            select(MaterialVersion)
            .where(MaterialVersion.material_id == material.id)
            .order_by(MaterialVersion.version_no.desc())
            .limit(1)
        )
        if not version or version.status != "extracted":
            continue
        previous = session.scalar(
            select(Job)
            .where(Job.kind == "embed", Job.payload["version_id"].as_string() == version.id)
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        if (
            not previous
            or previous.status not in {"failed", "queued", "waiting_ai"}
            or previous.payload.get("_ai_provider") not in {None, "ollama"}
        ):
            continue
        job = Job(
            owner_id=previous.owner_id,
            course_id=material.course_id,
            kind="embed",
            payload={"version_id": version.id, "previous_provider_job_id": previous.id},
        )
        session.add(job)
        session.flush()
        version.error_code = None
        if needs_remote(session, job):
            hold(session, job, "GEMINI_CALLS_DISABLED")
        session.add(
            AuditEvent(
                actor_id=previous.owner_id,
                action="material_provider_changed",
                target_id=material.id,
                detail={
                    "from": "ollama",
                    "to": "gemini",
                    "job_id": job.id,
                    "previous_job_id": previous.id,
                    "calls_enabled": False,
                },
            )
        )
        migrated.append(job.id)
    return migrated
