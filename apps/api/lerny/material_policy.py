"""Material purpose is derived from the instructor-selected kind, never a second toggle."""

from sqlalchemy import select

from lerny.config import settings
from lerny.models import Job, MaterialVersion

KINDS = {"lecture", "example", "assignment", "transcript", "past_exam", "answer"}


def internal_use_for(kind):
    if kind not in KINDS:
        raise ValueError("INVALID_MATERIAL_KIND")
    return "validation_grading" if kind == "answer" else "none"


def visibility_for(kind, requested):
    return "private" if kind == "answer" else requested


def student_source(material):
    return (material.visibility == "public" and material.internal_use == "none"
            and material.kind != "answer")


def refresh_processing(session, material, owner_id, was_student_source):
    """Newly eligible Gemini sources must finish indexing before being marked ready."""
    from lerny.automatic import enqueue_concepts, sync_progress
    from lerny.gemini_runtime import hold, pause_reason

    if settings().ai_provider == "gemini" and was_student_source != student_source(material):
        version = session.scalar(
            select(MaterialVersion)
            .where(MaterialVersion.material_id == material.id)
            .order_by(MaterialVersion.version_no.desc())
            .limit(1)
        )
        if version and version.status in {"ready", "extracted"} and version.extracted_text:
            job = session.scalar(
                select(Job)
                .where(
                    Job.kind == "embed",
                    Job.payload["version_id"].as_string() == version.id,
                    Job.payload["_ai_provider"].as_string() == "gemini",
                    Job.status.in_(["queued", "waiting_ai"]),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if not job:
                job = Job(
                    owner_id=owner_id,
                    course_id=material.course_id,
                    kind="embed",
                    payload={"version_id": version.id},
                )
                session.add(job)
                session.flush()
            version.status, version.error_code = "extracted", None
            reason = pause_reason()
            if student_source(material) and reason:
                hold(session, job, reason)
            else:
                job.status, job.error_code = "queued", None
    if material.active_version_id:
        enqueue_concepts(
            session, material, session.get(MaterialVersion, material.active_version_id), owner_id
        )
    sync_progress(session, material.course_id)
