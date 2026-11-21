import json
import secrets
from typing import Literal

from fastapi import APIRouter, Header, Query
from pydantic import Field
from sqlalchemy import func, select, text

from lerny.auth import Input
from lerny.models import ChatMessage, Course, Enrollment, Idempotency, Job, Section, grading_attempt, uid
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
    mode: Literal["theory", "practice"] = "theory"
    concept_id: str | None = None
    exercise_id: str | None = None
    plan_id: str | None = None
    practice_context: str = Field(default="", max_length=3000)


@router.post("/sections/{section_id}/chat/messages", status_code=202)
def ask(
    section_id: str,
    body: ChatInput,
    session: Db,
    actor: Actor,
    idempotency_key: str | None = Header(default=None),
):
    section = section_student(session, actor, section_id)
    context = {"mode": body.mode}
    if body.mode == "practice":
        from lerny.practice import assigned
        _, plan, exercise = assigned(session, actor, section_id, body.exercise_id, body.plan_id)
        context.update(exercise_id=exercise.id, concept_id=exercise.concept_id,
                       practice_session_id=plan.id, student_context=body.practice_context,
                       practice_title=exercise.title, practice_week=plan.week)
    elif body.exercise_id or body.practice_context:
        deny(422, "실습 질문에는 현재 배정된 실습 문제가 필요합니다.")
    elif body.concept_id:
        from lerny.models import Concept
        from lerny.weekly_content import published_concept_ids
        concept = session.get(Concept, body.concept_id)
        if not concept or concept.course_id != section.course_id or concept.id not in section.progress or concept.id not in published_concept_ids(session,section.course_id):
            deny(404)
        context["concept_id"] = concept.id
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
            learning_context=context,
            access_epoch=course.access_epoch,
        )
        session.add(message)
        if body.mode == "practice":
            from lerny.courses import audit
            audit(session, actor, "practice_help", context["practice_session_id"],
                  {"exercise_id": context["exercise_id"], "kind": "chat"})
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
    if job.kind == "material_preview":
        deny(404)  # Internal storage keys are available only through authorized preview routes.
    if job.kind in {"lecture_spec", "lecture_grounding", "narration_lesson", "lecture_slides"}:
        # This route cannot revalidate lecture source snapshots. Use dedicated staff-only intake.
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
        attempt = grading_attempt(session, job)
        attempt.status = "held"
        attempt.feedback = {"message": "채점 요청이 취소되어 검토 보류했어요."}
    if job.kind == "practice_grade":
        from lerny.models import PracticeAttempt
        attempt = session.get(PracticeAttempt, job.payload["attempt_id"])
        attempt.status = "held"
        attempt.feedback = {"message": "검증 요청이 취소되어 보류했어요."}
    session.commit()
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, session: Db, actor: Actor):
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.owner_id != actor.id:
        deny(404)
    if job.kind in {"lecture_spec", "lecture_grounding", "narration_lesson", "lecture_slides"}:
        deny(409, "강의 명세는 전용 검증 경로로 다시 제출해 주세요.")
    course_access(session, actor, job.course_id)
    if job.status != "failed":
        deny(409)
    from lerny.gemini_failures import prepare_retry
    prepare_retry(job)
    job.status, job.error_code = "queued", None
    if job.kind in {"extract", "embed"}:
        from lerny.models import MaterialVersion
        version = session.get(MaterialVersion, job.payload["version_id"])
        version.status = "extracted" if job.kind == "embed" else "queued"
        version.error_code = None
    if job.kind == "grade":
        attempt = grading_attempt(session, job)
        if attempt.status != "held":
            deny(409, "이미 처리된 답안은 다시 채점할 수 없습니다.")
        attempt.status = "pending"
    if job.kind == "practice_grade":
        from lerny.models import PracticeAttempt
        attempt = session.get(PracticeAttempt, job.payload["attempt_id"])
        if attempt.status != "held":
            deny(409, "이미 처리된 답안은 다시 검증할 수 없습니다.")
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
                "feedback": (m.feedback or {}).get("value"),
                "context": {key: (m.learning_context or {}).get(key) for key in
                            ("mode", "exercise_id", "practice_title", "practice_week")},
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
    mode: Literal["theory", "practice"] | None = None,
):
    section = section_student(session, actor, section_id)
    epoch = session.get(Course, section.course_id).access_epoch
    query = select(ChatMessage).where(
        ChatMessage.student_id == actor.id, ChatMessage.section_id == section_id
    )
    if mode:
        query = query.where(ChatMessage.learning_context["mode"].as_string() == mode)
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
                "feedback": (m.feedback or {}).get("value"),
                "context": {key: (m.learning_context or {}).get(key) for key in
                            ("mode", "exercise_id", "practice_title", "practice_week")},
                "answer": m.answer if m.access_epoch == epoch else None,
                "error": None
                if (m.answer and m.access_epoch == epoch)
                or (pending and pending.payload.get("message_id") == m.id)
                else "답변이 없거나 자료가 변경됐어요. 다시 질문해 주세요.",
            }
            for m in reversed(messages)
        ],
    }


class ChatFeedback(Input):
    value: Literal["understood", "confused", "aborted"]


@router.put("/sections/{section_id}/chat/messages/{message_id}/feedback")
def chat_feedback(section_id: str, message_id: str, body: ChatFeedback, session: Db, actor: Actor):
    section = section_student(session, actor, section_id)
    message = session.scalar(select(ChatMessage).where(ChatMessage.id == message_id,
        ChatMessage.student_id == actor.id, ChatMessage.section_id == section_id).with_for_update())
    if not message:
        deny(404)
    if not message.answer or message.access_epoch != session.get(Course, section.course_id).access_epoch:
        deny(409, "현재 자료로 작성된 답변이 도착한 뒤 평가해 주세요.")
    if (message.feedback or {}).get("value") != body.value:
        from lerny.models import now
        message.feedback = {"value": body.value, "updated_at": now().isoformat()}
        session.commit()
    return {"message_id": message.id, "value": body.value}
