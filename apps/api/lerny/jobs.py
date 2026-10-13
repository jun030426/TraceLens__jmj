import json
import secrets

from fastapi import APIRouter, Header, Query
from pydantic import Field
from sqlalchemy import func, select, text

from lerny.auth import Input
from lerny.models import Attempt, ChatMessage, Course, Enrollment, Idempotency, Job, Section, uid
from lerny.security import Actor, Db, course_access, deny, digest, staff_access

router = APIRouter(prefix="/api/v1")


def idempotent(session, actor, scope, key, payload, make):
    if not key or len(key) > 100:
        deny(400, "Idempotency-Key가 필요합니다.")
    request_hash = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    # PostgreSQL transaction lock serializes identical scoped keys before inserting records.
    lock = int(digest(actor.id + scope + key)[:15], 16)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    item = session.scalar(
        select(Idempotency).where(
            Idempotency.user_id == actor.id, Idempotency.scope == scope, Idempotency.key == key
        )
    )
    if item:
        if not secrets.compare_digest(item.request_hash, request_hash):
            deny(409, "같은 요청 키에 다른 내용이 들어왔습니다.")
        return item.response
    response = make()
    session.add(
        Idempotency(
            user_id=actor.id, scope=scope, key=key, request_hash=request_hash, response=response
        )
    )
    session.commit()
    return response


def section_student(session, actor, section_id):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    enrollment = session.scalar(
        select(Enrollment).where(
            Enrollment.student_id == actor.id,
            Enrollment.section_id == section_id,
            Enrollment.status == "active",
        )
    )
    if not enrollment:
        deny(404, "수강 중인 강의실이 아닙니다.")
    return section


class ChatInput(Input):
    thread_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


@router.post("/sections/{section_id}/chat/messages", status_code=202)
def ask(
    section_id: str,
    body: ChatInput,
    session: Db,
    actor: Actor,
    idempotency_key: str | None = Header(default=None),
):
    section = section_student(session, actor, section_id)
    if body.thread_id:
        thread = session.scalar(
            select(ChatMessage).where(
                ChatMessage.thread_id == body.thread_id,
                ChatMessage.student_id == actor.id,
                ChatMessage.section_id == section_id,
            )
        )
        if not thread:
            deny(404)

    def make():
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int(digest("chat:" + actor.id)[:15], 16)},
        )
        pending = session.scalar(
            select(Job)
            .where(
                Job.owner_id == actor.id, Job.kind == "chat", Job.status.in_(["queued", "running", "waiting_ai"])
            )
            .limit(1)
        )
        if pending:
            deny(429, "이전 질문의 답변을 기다려 주세요.")
        course = session.get(Course, section.course_id)
        message = ChatMessage(
            student_id=actor.id,
            section_id=section_id,
            thread_id=body.thread_id or uid(),
            question=body.message,
            access_epoch=course.access_epoch,
        )
        session.add(message)
        session.flush()
        job = Job(
            owner_id=actor.id,
            course_id=section.course_id,
            kind="chat",
            payload={"message_id": message.id},
        )
        session.add(job)
        session.flush()
        return {
            "job_id": job.id,
            "status": "queued",
            "resource_id": message.id,
            "thread_id": message.thread_id,
            "poll_url": f"/api/v1/jobs/{job.id}",
        }

    return idempotent(
        session, actor, "chat:" + section_id, idempotency_key, body.model_dump(), make
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Db, actor: Actor):
    job = session.get(Job, job_id)
    if not job:
        deny(404)
    course_access(session, actor, job.course_id)
    if job.owner_id != actor.id:
        staff_access(session, actor, job.course_id)
        if job.kind != "extract":
            deny(404)
    result = job.result
    if job.kind == "chat" and result:
        course = session.get(Course, job.course_id)
        if result.get("access_epoch") != course.access_epoch:
            result = {
                "answer_kind": "insufficient",
                "answer": "자료 공개 범위가 변경되어 답변을 다시 요청해 주세요.",
                "citations": [],
            }
    from lerny.cloud_jobs import ai_status
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempt": job.attempt,
        "result": result,
        "error": {"code": job.error_code, "retryable": True} if job.error_code else None,
        "ai_status": ai_status(session) if job.status == "waiting_ai" else None,
    }


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, session: Db, actor: Actor):
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.owner_id != actor.id:
        deny(404)
    course_access(session, actor, job.course_id)
    if job.status not in ("queued", "running", "waiting_ai"):
        deny(409)
    job.status, job.lease_token = "cancelled", None
    if job.kind == "grade":
        attempt = session.get(Attempt, job.payload["attempt_id"])
        attempt.status = "held"
        attempt.feedback = {"message": "채점 요청이 취소되어 검토 보류했어요."}
    session.commit()
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, session: Db, actor: Actor):
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.owner_id != actor.id:
        deny(404)
    course_access(session, actor, job.course_id)
    if job.status != "failed":
        deny(409)
    job.status, job.error_code = "queued", None
    job.payload = {**job.payload, "_ai_generation": job.payload.get("_ai_generation", 0) + 1}
    if job.kind in {"extract", "embed"}:
        from lerny.models import MaterialVersion
        version = session.get(MaterialVersion, job.payload["version_id"])
        version.status = "extracted" if job.kind == "embed" else "queued"
        version.error_code = None
    if job.kind == "grade":
        attempt = session.get(Attempt, job.payload["attempt_id"])
        if attempt.status != "held":
            deny(409, "이미 처리된 답안은 다시 채점할 수 없습니다.")
        attempt.status = "pending"
    session.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/chat/threads/{thread_id}")
def chat_thread(thread_id: str, session: Db, actor: Actor):
    messages = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id, ChatMessage.student_id == actor.id)
            .order_by(ChatMessage.created_at)
        )
    )
    if not messages:
        deny(404)
    section = section_student(session, actor, messages[0].section_id)
    course = session.get(Course, section.course_id)
    return {
        "items": [
            {
                "id": m.id,
                "question": m.question,
                "answer": m.answer if m.access_epoch == course.access_epoch else None,
            }
            for m in messages
        ]
    }


@router.get("/sections/{section_id}/chat/history")
def chat_history(
    section_id: str, session: Db, actor: Actor,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=50),
    q: str = Query(default="", max_length=200),
    thread_id: str | None = Query(default=None, max_length=36),
    latest_thread: bool = False,
):
    section = section_student(session, actor, section_id)
    epoch = session.get(Course, section.course_id).access_epoch
    query = select(ChatMessage).where(
        ChatMessage.student_id == actor.id, ChatMessage.section_id == section_id
    )
    if latest_thread and not thread_id:
        thread_id = session.scalar(
            select(ChatMessage.thread_id)
            .where(ChatMessage.student_id == actor.id, ChatMessage.section_id == section_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
    if thread_id:
        query = query.where(ChatMessage.thread_id == thread_id)
    if q.strip():
        query = query.where(ChatMessage.question.icontains(q.strip(), autoescape=True))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    messages = list(session.scalars(query.order_by(
        ChatMessage.created_at.desc(), ChatMessage.id.desc()
    ).offset(offset).limit(limit)))
    pending = session.scalar(
        select(Job)
        .where(
            Job.owner_id == actor.id,
            Job.course_id == section.course_id,
            Job.kind == "chat",
            Job.status.in_(["queued", "running", "waiting_ai"]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(messages) < total,
        "thread_id": messages[0].thread_id if messages else None,
        "job_id": pending.id
        if pending and any(m.id == pending.payload.get("message_id") for m in messages)
        else None,
        "items": [
            {
                "id": m.id,
                "created_at": m.created_at,
                "question": m.question,
                "answer": m.answer if m.access_epoch == epoch else None,
                "error": None
                if (m.answer and m.access_epoch == epoch)
                or (pending and pending.payload.get("message_id") == m.id)
                else "답변이 없거나 자료가 변경됐어요. 다시 질문해 주세요.",
            }
            for m in reversed(messages)
        ],
    }
