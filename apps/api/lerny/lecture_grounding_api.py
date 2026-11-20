"""Explicit staff-only grounding requests; polling rechecks current source access."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select

from lerny.config import settings
from lerny.lecture_grounding import REVIEW_VERSION, grounding_inputs, spec_hash
from lerny.lecture_specs import get_request, snapshot_is_current
from lerny.models import Job
from lerny.security import Actor, Db, deny

router = APIRouter(prefix="/api/v1/courses/{course_id}/lecture-spec-requests")


@router.post("/{request_id}/grounding", status_code=202)
def request_grounding(course_id: str, request_id: str, session: Db, actor: Actor):
    course, parent = get_request(session, actor, course_id, request_id, lock=True)
    if not snapshot_is_current(session, course, parent.payload):
        deny(409, "자료가 변경됐습니다. 새 강의 명세 요청이 필요합니다.")
    if (
        not parent.result
        or not parent.result.get("spec")
        or parent.result["validation"]["status"] != "needs_content_review"
    ):
        deny(409, "구조 검증을 통과한 초안을 먼저 제출해 주세요.")
    fingerprint = spec_hash(parent.result["spec"])
    candidates = session.scalars(
        select(Job)
        .where(
            Job.course_id == course_id,
            Job.owner_id == actor.id,
            Job.kind == "lecture_grounding",
            Job.payload["lecture_request_id"].as_string() == parent.id,
            Job.status.in_(["queued", "running", "waiting_ai", "succeeded"]),
        )
        .order_by(Job.created_at.desc())
    )
    job = next(
        (
            item
            for item in candidates
            if item.payload["spec_hash"] == fingerprint
            and item.payload["review_version"] == REVIEW_VERSION
            and item.payload["model"] == settings().model_name
        ),
        None,
    )
    if job is None:
        job = Job(
            owner_id=actor.id,
            course_id=course_id,
            kind="lecture_grounding",
            status="queued",
            payload={
                "lecture_request_id": parent.id,
                "spec_hash": fingerprint,
                "review_version": REVIEW_VERSION,
                "model": settings().model_name,
            },
        )
        session.add(job)
        session.flush()
    session.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "render_allowed": False,
        "poll_url": f"/api/v1/courses/{course_id}/lecture-spec-requests/{request_id}/grounding/{job.id}",
    }


@router.get("/{request_id}/grounding/{job_id}")
def get_grounding(course_id: str, request_id: str, job_id: str, session: Db, actor: Actor):
    get_request(session, actor, course_id, request_id)
    job = session.get(Job, job_id)
    if (
        not job
        or job.kind != "lecture_grounding"
        or job.course_id != course_id
        or job.payload["lecture_request_id"] != request_id
    ):
        deny(404)
    try:
        grounding_inputs(session, job)
    except ValueError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "job_id": job.id,
                "result": None,
                "error": {"code": str(exc)},
                "render_allowed": False,
            },
        )
    return {
        "job_id": job.id,
        "status": job.status,
        "result": job.result if job.status == "succeeded" else None,
        "error": {"code": job.error_code} if job.error_code else None,
        "render_allowed": False,
        "publication_allowed": False,
    }
