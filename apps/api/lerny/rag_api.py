"""Authenticated local index status/rebuild; no corpus or SQLite overwrite."""

from fastapi import APIRouter, Header
from sqlalchemy import select

from lerny.config import settings
from lerny.gemini_provider import PROFILE, available
from lerny.jobs import idempotent
from lerny.models import Course, Job, User
from lerny.rag_index import indexed_ids
from lerny.retrieval import public_rows
from lerny.security import Actor, Db, deny, staff_access

router = APIRouter(prefix="/api/v1", tags=["local-rag"])


@router.get("/courses/{course_id}/rag/status")
def status(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    rows = public_rows(session, course_id)
    indexed = len(indexed_ids(row[0] for row in rows))
    return {
        "provider": settings().ai_provider,
        "storage": settings().rag_storage,
        "profile": PROFILE,
        "eligible_chunks": len(rows),
        "indexed_chunks": indexed,
        "index_ready": bool(rows) and indexed == len(rows),
        "calls_enabled": settings().gemini_calls_enabled,
        "key_configured": settings().gemini_keys_ready("embedding"),
    }


@router.post("/courses/{course_id}/rag/reindex", status_code=202)
def reindex(
    course_id: str, session: Db, actor: Actor, idempotency_key: str | None = Header(default=None)
):
    course = staff_access(session, actor, course_id)
    if settings().ai_provider != "gemini":
        deny(409, "Gemini 공급자를 선택한 로컬 환경에서 실행해 주세요.")
    try:
        available("embedding")
    except ValueError as exc:
        deny(409, str(exc))

    def make():
        job = Job(
            owner_id=actor.id,
            course_id=course_id,
            kind="rag_reindex",
            payload={"profile": PROFILE, "access_epoch": course.access_epoch},
        )
        session.add(job)
        session.flush()
        return {"job_id": job.id, "status": "queued", "poll_url": f"/api/v1/jobs/{job.id}"}

    return idempotent(
        session,
        actor,
        "rag_reindex:" + course_id,
        idempotency_key,
        {"profile": PROFILE, "access_epoch": course.access_epoch},
        make,
    )


def reindex_job(session, job):
    from lerny.worker import embed_chunks

    actor = session.get(User, job.owner_id, populate_existing=True)
    if not actor or not actor.active:
        raise ValueError("ACCESS_REVOKED")
    course = staff_access(session, actor, job.course_id)
    if settings().ai_provider != "gemini" or job.payload["profile"] != PROFILE:
        raise ValueError("PROVIDER_CHANGED")
    if course.access_epoch != job.payload["access_epoch"]:
        raise ValueError("SOURCE_CHANGED")
    rows = public_rows(session, course.id)
    present = indexed_ids(row[0] for row in rows)
    pending = [row[0] for row in rows if row[0].id not in present]
    batch = pending[: settings().gemini_max_calls_per_job]
    for chunk in batch:
        session.refresh(course)
        session.refresh(actor)
        if not actor.active:
            raise ValueError("ACCESS_REVOKED")
        staff_access(session, actor, course.id)
        if course.access_epoch != job.payload["access_epoch"]:
            raise ValueError("SOURCE_CHANGED")
        embed_chunks([chunk], session)
    current = session.scalar(
        select(Course)
        .where(Course.id == course.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if current.access_epoch != job.payload["access_epoch"]:
        raise ValueError("SOURCE_CHANGED")
    indexed = len(indexed_ids(row[0] for row in rows))
    return {
        "profile": PROFILE,
        "eligible_chunks": len(rows),
        "indexed_chunks": indexed,
        "remaining_chunks": len(rows) - indexed,
        "index_ready": bool(rows) and indexed == len(rows),
        "access_epoch": current.access_epoch,
    }
