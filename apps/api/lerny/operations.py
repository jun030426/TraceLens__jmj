"""Shared admission/claim gates. The singleton row serializes drain and job claims."""

import os
import re
import socket
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from lerny.admin_models import OperationsState, OperationsWorker
from lerny.config import settings
from lerny.models import CodeRun, ConceptVideo, Job, ModelCall, now

FEATURES = ("uploads", "rag", "grading", "content", "videos")
JOB_FEATURE = {
    "material_preview": "uploads",
    "extract": "uploads",
    "embed": "uploads",
    "rag_reindex": "uploads",
    "chat": "rag",
    "grade": "grading",
    "practice_grade": "grading",
    "narration_lesson": "videos",
    "lecture_grounding": "videos",
    "lecture_spec": "videos",
}


def state(session, *, lock=False):
    row = session.scalar(
        select(OperationsState).where(OperationsState.id == 1).with_for_update()
        if lock
        else select(OperationsState).where(OperationsState.id == 1)
    )
    if row is None:
        session.execute(
            insert(OperationsState)
            .values(
                id=1,
                revision=1,
                maintenance=False,
                message="현재 서비스 점검 중입니다. 잠시 후 다시 이용해 주세요.",
                features={},
                server_hold=False,
            )
            .on_conflict_do_nothing()
        )
        row = session.scalar(
            select(OperationsState).where(OperationsState.id == 1).with_for_update()
        )
    return row


def enabled(row, feature):
    return not row.maintenance and not row.server_hold and row.features.get(feature, True)


def allowed_job_kinds(row):
    known = {
        "material_preview",
        "extract",
        "embed",
        "auto_concepts",
        "weekly_content",
        "chat",
        "questions",
        "grade",
        "lecture_grounding",
        "rag_reindex",
        "narration_lesson",
        "daily_theory",
        "practice_prepare",
        "practice_grade",
        "lecture_spec",
        "lecture_slides",
    }
    return [kind for kind in known if enabled(row, JOB_FEATURE.get(kind, "content"))]


def touch(session, kind, ready=True, busy=False):
    worker_id = f"{kind}:{socket.gethostname()}:{os.getpid()}"[:100]
    server_id = settings().admin_instance_id if settings().dedicated_worker else None
    session.execute(
        insert(OperationsWorker)
        .values(
            id=worker_id, kind=kind, server_id=server_id, last_seen_at=now(), ready=ready, busy=busy
        )
        .on_conflict_do_update(
            index_elements=[OperationsWorker.id],
            set_={"last_seen_at": now(), "ready": ready, "busy": busy, "server_id": server_id},
        )
    )


def finished(kind):
    from sqlalchemy.orm import Session

    from lerny.db import engine

    with Session(engine()) as session:
        touch(session, kind)
        session.commit()


def public_state(row):
    return {
        "revision": row.revision,
        "maintenance": row.maintenance,
        "message": row.message if row.maintenance else "",
        "features": {key: enabled(row, key) for key in FEATURES},
        "server_hold": row.server_hold,
    }


def request_feature(path):
    if "/lecture-slides" in path:
        return "content"
    if re.search(r"/(uploads|materials)(/[^/]+/versions)?$", path) or "/uploads/" in path:
        return "uploads"
    if path.endswith(("/versions", "/transcript")) or "/rag/reindex" in path:
        return "uploads"
    if "/concept-videos/" in path or "/narration" in path or "/lecture-" in path:
        return "videos"
    if "/chat" in path or path.endswith("/help") or "/trace" in path:
        return "rag" if "/trace" not in path else "grading"
    if path.endswith(("/submit", "/appeal")):
        return "grading"
    if path.endswith(("/daily", "/generate", "/learning")):
        return "content"
    if "/content-generations/" in path or re.search(r"/weeks/\d+/content$", path):
        return "content"
    return None


def guard_request(session, request):
    path = request.url.path
    if request.method in {"GET", "HEAD", "OPTIONS"} or path.startswith(
        ("/api/v1/admin/", "/api/v1/ops/", "/api/v1/auth/", "/api/v1/me")
    ):
        return
    row = state(session)
    feature = request_feature(path)
    retry = re.fullmatch(r"/api/v1/jobs/([^/]+)/retry", path)
    if retry:
        job = session.get(Job, retry.group(1))
        feature = JOB_FEATURE.get(job.kind, "content") if job else None
    if row.maintenance or (feature and not enabled(row, feature)):
        raise HTTPException(
            503,
            row.message
            if row.maintenance
            else "해당 기능은 운영 점검으로 잠시 중지됐어요. 기존 기록은 확인할 수 있어요.",
        )


def busy_counts(session):
    # Include retained leases after cancellation: work can still be executing until the lease ends.
    live = now()
    return {
        "workers": session.scalar(
            select(func.count())
            .select_from(OperationsWorker)
            .where(OperationsWorker.busy.is_(True))
        ),
        "jobs": session.scalar(
            select(func.count())
            .select_from(Job)
            .where(or_(Job.status == "running", Job.lease_until > live))
        ),
        "code": session.scalar(
            select(func.count())
            .select_from(CodeRun)
            .where(or_(CodeRun.status == "running", CodeRun.lease_until > live))
        ),
        "model": session.scalar(
            select(func.count())
            .select_from(ModelCall)
            .where(or_(ModelCall.status == "running", ModelCall.lease_until > live))
        ),
        "video": session.scalar(
            select(func.count())
            .select_from(ConceptVideo)
            .where(or_(ConceptVideo.status == "submitting", ConceptVideo.lease_until > live))
        ),
    }


def workers_ready(session, since=None):
    cutoff = max(now() - timedelta(seconds=90), since) if since else now() - timedelta(seconds=90)
    query = select(OperationsWorker.kind).where(
        OperationsWorker.last_seen_at > cutoff, OperationsWorker.ready.is_(True)
    )
    if settings().admin_instance_id:
        query = query.where(OperationsWorker.server_id == settings().admin_instance_id)
    kinds = set(session.scalars(query))
    return {"material", "code", "video"}.issubset(kinds)
