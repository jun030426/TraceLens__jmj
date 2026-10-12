"""Grounded theory sessions, durable assessment and concept-level review."""

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Header, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import func, select, text

from lerny.auth import Input
from lerny.courses import audit
from lerny.jobs import idempotent, section_student
from lerny.models import (
    Attempt,
    Chunk,
    Concept,
    Enrollment,
    Job,
    LearningSession,
    LearningCompletion,
    Material,
    MaterialVersion,
    Question,
    Review,
    Section,
    User,
    now,
)
from lerny.security import Actor, Db, deny, digest, match_revision, staff_access

router = APIRouter(prefix="/api/v1")


def record_completion(session, student_id, section_id, domain, source_id, completed_at):
    """Internal: only after a validated complete final submission, never execution."""
    if domain not in ("theory", "practice"):
        raise ValueError("Unsupported learning domain")
    lock_student(session, student_id)
    existing = session.scalar(select(LearningCompletion).where(
        LearningCompletion.student_id == student_id,
        LearningCompletion.domain == domain,
        LearningCompletion.source_id == source_id))
    if existing:
        return existing
    item = LearningCompletion(student_id=student_id, section_id=section_id,
        domain=domain, source_id=source_id,
        day=(completed_at + timedelta(hours=9)).date(), created_at=completed_at)
    session.add(item)
    session.flush()
    return item


def streak_summary(days, current_day):
    days = set(days)
    cursor = current_day if current_day in days else current_day - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return {"today_completed": current_day in days, "current_streak": streak,
            "total_days": len(days), "days": sorted(days, reverse=True)}


@router.get("/my/learning-streak")
def learning_streak(session: Db, actor: Actor):
    if actor.role != "student":
        deny(403)
    days = session.scalars(select(LearningCompletion.day).where(
        LearningCompletion.student_id == actor.id))
    return streak_summary(days, today())


@router.get("/my/learning-sessions")
def learning_history(
    session: Db, actor: Actor, section_id: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
):
    if actor.role != "student":
        deny(403)
    if section_id:
        section_student(session, actor, section_id)
    if date_from and date_to and date_from > date_to:
        deny(422, "시작일은 종료일 이전이어야 해요.")
    active_sections = select(Enrollment.section_id).where(
        Enrollment.student_id == actor.id, Enrollment.status == "active"
    )
    query = select(LearningSession).where(
        LearningSession.student_id == actor.id, LearningSession.section_id.in_(active_sections)
    )
    if section_id:
        query = query.where(LearningSession.section_id == section_id)
    if date_from:
        query = query.where(LearningSession.day >= date_from)
    if date_to:
        query = query.where(LearningSession.day <= date_to)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    records = session.scalars(query.order_by(LearningSession.day.desc(), LearningSession.id.desc())
                              .offset(offset).limit(limit))
    items = []
    for record in records:
        attempts = list(
            session.scalars(select(Attempt).where(Attempt.learning_session_id == record.id))
        )
        valid = [a for a in attempts if a.status == "graded" and a.independent]
        items.append(
            {
                "id": record.id,
                "section_id": record.section_id,
                "day": record.day,
                "total": len(record.question_ids),
                "submitted": len(attempts),
                "pending": sum(a.status in ("pending", "held") for a in attempts),
                "valid": len(valid),
                "correct": sum(bool(a.correct) for a in valid),
            }
        )
    return {"items": items, "total": total, "offset": offset, "limit": limit,
            "has_more": offset + len(items) < total}


@router.get("/learning-sessions/{learning_id}")
def read_learning_session(learning_id: str, session: Db, actor: Actor):
    record = session.get(LearningSession, learning_id)
    if not record or record.student_id != actor.id:
        deny(404)
    section_student(session, actor, record.section_id)
    return session_view(session, record)


def today():
    # Fixed KST offset avoids a Windows system time-zone database dependency.
    return (now() + timedelta(hours=9)).date()


def lock_student(session, student_id):
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int(digest("learning:" + student_id)[:15], 16)},
    )


def valid_sources(session, question, max_week=None):
    if not question.sources:
        return False
    for source in question.sources:
        chunk = session.get(Chunk, source.get("chunk_id"))
        if not chunk:
            return False
        version = session.get(MaterialVersion, chunk.version_id)
        material = session.get(Material, version.material_id)
        if (
            (max_week is not None and material.week > max_week)
            or material.course_id != question.course_id
            or material.deleted
            or material.visibility != "public"
            or material.active_version_id != version.id
            or source.get("quote", "") not in chunk.content
            or not source.get("quote")
        ):
            return False
    return True


def question_view(q, teacher=False):
    result = {
        "id": q.id,
        "concept_id": q.concept_id,
        "kind": q.kind,
        "prompt": q.prompt,
        "options": q.options,
        "revision": q.revision,
        "status": q.status,
    }
    if teacher:
        result.update(solution=q.solution, sources=q.sources)
    return result


class GenerateInput(Input):
    concept_id: str


@router.post("/courses/{course_id}/questions/generate", status_code=202)
def generate(
    course_id: str,
    body: GenerateInput,
    session: Db,
    actor: Actor,
    idempotency_key: str | None = Header(default=None),
):
    staff_access(session, actor, course_id)
    concept = session.get(Concept, body.concept_id)
    if not concept or concept.course_id != course_id:
        deny(404)

    def make():
        job = Job(
            owner_id=actor.id, course_id=course_id, kind="questions", payload=body.model_dump()
        )
        session.add(job)
        session.flush()
        return {"job_id": job.id, "status": "queued"}

    return idempotent(
        session, actor, "question-generation:" + course_id, idempotency_key, body.model_dump(), make
    )


@router.get("/courses/{course_id}/questions")
def questions(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    rows = session.scalars(
        select(Question).where(Question.course_id == course_id).order_by(Question.created_at.desc())
    )
    return {
        "items": [
            {**question_view(q, True), "sources_current": valid_sources(session, q)} for q in rows
        ]
    }


class QuestionState(Input):
    status: Literal["active", "stopped"]


@router.patch("/questions/{question_id}")
def question_state(
    question_id: str,
    body: QuestionState,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    q = session.scalar(select(Question).where(Question.id == question_id).with_for_update())
    if not q:
        deny(404)
    staff_access(session, actor, q.course_id)
    match_revision(q.revision, if_match)
    if body.status == "active" and not valid_sources(session, q):
        deny(409, "현재 공개된 근거로 다시 생성해 주세요.")
    q.status, q.revision = body.status, q.revision + 1
    session.commit()
    return question_view(q, True)


def session_view(session, learning):
    items = []
    for question_id in learning.question_ids:
        q = session.get(Question, question_id)
        attempt = session.scalar(
            select(Attempt).where(
                Attempt.learning_session_id == learning.id, Attempt.question_id == question_id
            )
        )
        available = q.status == "active" and valid_sources(session, q)
        item = (
            question_view(q)
            if available
            else {
                "id": q.id,
                "status": "unavailable",
                "prompt": "자료 또는 문항이 변경되어 사용할 수 없는 문제예요.",
            }
        )
        item["attempt"] = attempt_view(attempt) if attempt else None
        if not available and item["attempt"]:
            item["attempt"]["feedback"] = None
        if attempt and attempt.status == "graded" and available:
            item["explanation"] = q.solution.get("explanation", "")
            if q.kind == "mcq":
                item["correct_option"] = q.options[q.solution["answer_index"]]
        if attempt and available:
            item["submitted_answer"] = (
                q.options[int(attempt.answer)] if q.kind == "mcq" else attempt.answer
            )
        items.append(item)
    return {
        "id": learning.id,
        "section_id": learning.section_id,
        "day": learning.day,
        "items": items,
        "target_count": 3,
        "shortage": max(0, 3 - len(items)),
    }


@router.post("/sections/{section_id}/daily")
def daily(section_id: str, session: Db, actor: Actor):
    section = section_student(session, actor, section_id)
    from lerny.automatic import sync_progress
    sync_progress(session, section.course_id)
    lock_student(session, actor.id)
    learning = session.scalar(
        select(LearningSession).where(
            LearningSession.student_id == actor.id,
            LearningSession.section_id == section_id,
            LearningSession.day == today(),
        )
    )
    if learning:
        return session_view(session, learning)
    if not section.progress:
        deny(409, "공개된 강의 자료에서 학습 콘텐츠를 준비 중이에요. 준비가 끝나면 학습을 시작할 수 있어요.")
    reviews = {
        r.concept_id: r
        for r in session.scalars(
            select(Review).where(Review.student_id == actor.id, Review.due_on <= today())
        )
    }
    seen = set(session.scalars(select(Attempt.question_id).where(Attempt.student_id == actor.id)))
    from lerny.automatic import calendar_week
    max_week = calendar_week(session, section) if section.progress_mode == "auto" else section.progress_week
    bank = [
        q
        for q in session.scalars(
            select(Question)
            .where(
                Question.course_id == section.course_id,
                Question.status == "active",
                Question.concept_id.in_(section.progress),
            )
            .order_by(Question.created_at)
        )
        if valid_sources(session, q, max_week)
    ]
    chosen = []
    # One new item, then two review items; fallback to other eligible concepts.
    for kind, prefer_review in [("mcq", False), ("mcq", True), ("essay", True)]:
        candidates = [q for q in bank if q.kind == kind and q.id not in chosen]
        candidates.sort(
            key=lambda q: (
                q.concept_id not in reviews if prefer_review else q.id in seen,
                q.id in seen,
                q.created_at,
            )
        )
        if candidates:
            chosen.append(candidates[0].id)
    if not chosen:
        deny(409, "현재 진도에 맞는 검증된 문항이 아직 없어요.")
    learning = LearningSession(
        student_id=actor.id, section_id=section_id, day=today(), question_ids=chosen
    )
    session.add(learning)
    session.commit()
    return session_view(session, learning)


def attempt_view(a):
    return {
        "id": a.id,
        "status": a.status,
        "score": a.score,
        "correct": a.correct,
        "feedback": a.feedback,
        "independent": a.independent,
        "appealed": a.appealed,
    }


def apply_review(session, attempt):
    if attempt.review_applied or attempt.status != "graded":
        return
    lock_student(session, attempt.student_id)
    day = session.get(LearningSession, attempt.learning_session_id).day
    review = session.scalar(
        select(Review)
        .where(Review.student_id == attempt.student_id, Review.concept_id == attempt.concept_id)
        .with_for_update()
    )
    if not review:
        review = Review(student_id=attempt.student_id, concept_id=attempt.concept_id, stage=0)
        session.add(review)
    if not attempt.correct or not attempt.independent:
        review.stage, review.due_on = 0, day + timedelta(days=1)
    elif review.last_attempt_day != day:
        if review.due_on is None and review.stage == 0:
            review.due_on = day + timedelta(days=1)
        elif review.due_on and day >= review.due_on:
            review.stage += 1
            review.due_on = (
                day + timedelta(days=3 if review.stage == 1 else 7) if review.stage < 3 else None
            )
    review.last_attempt_day = day
    attempt.review_applied = True


class AnswerInput(Input):
    answer: str = Field(min_length=1, max_length=4000)


@router.post("/learning-sessions/{learning_id}/questions/{question_id}/submit", status_code=202)
def submit(
    learning_id: str,
    question_id: str,
    body: AnswerInput,
    session: Db,
    actor: Actor,
    idempotency_key: str | None = Header(default=None),
):
    learning = session.get(LearningSession, learning_id)
    if not learning or learning.student_id != actor.id or question_id not in learning.question_ids:
        deny(404)
    section_student(session, actor, learning.section_id)
    q = session.get(Question, question_id)
    if q.status != "active" or not valid_sources(session, q):
        deny(409, "근거 자료가 변경된 문항입니다.")

    def make():
        lock_student(session, actor.id)
        existing = session.scalar(
            select(Attempt).where(
                Attempt.learning_session_id == learning_id, Attempt.question_id == question_id
            )
        )
        if existing:
            deny(409, "이미 제출한 문제예요.")
        # Reusing a previously disclosed question cannot establish independent mastery.
        prior = session.scalar(
            select(Attempt.id)
            .where(Attempt.student_id == actor.id, Attempt.question_id == question_id)
            .limit(1)
        )
        attempt = Attempt(
            student_id=actor.id,
            section_id=learning.section_id,
            learning_session_id=learning_id,
            question_id=q.id,
            concept_id=q.concept_id,
            answer=body.answer,
            independent=prior is None,
        )
        session.add(attempt)
        session.flush()
        job_id = None
        if q.kind == "mcq":
            if body.answer not in {str(i) for i in range(len(q.options))}:
                deny(422, "보기 중 하나를 선택해 주세요.")
            attempt.correct = int(body.answer) == q.solution["answer_index"]
            attempt.score, attempt.status = (100 if attempt.correct else 0), "graded"
            attempt.feedback = {
                "message": "정답이에요."
                if attempt.correct
                else "해설을 확인하고 내일 다시 복습해 봐요."
            }
            apply_review(session, attempt)
        else:
            job = Job(
                owner_id=actor.id,
                course_id=q.course_id,
                kind="grade",
                payload={"attempt_id": attempt.id},
            )
            session.add(job)
            session.flush()
            job_id = job.id
        submitted_ids = set(session.scalars(select(Attempt.question_id).where(
            Attempt.learning_session_id == learning_id)))
        if learning.question_ids and set(learning.question_ids) <= submitted_ids:
            record_completion(session, actor.id, learning.section_id, "theory", learning.id, now())
        return {"attempt_id": attempt.id, "job_id": job_id, "status": attempt.status}

    return idempotent(
        session,
        actor,
        "submit:" + learning_id + ":" + question_id,
        idempotency_key,
        body.model_dump(),
        make,
    )


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, session: Db, actor: Actor):
    a = session.get(Attempt, attempt_id)
    if not a:
        deny(404)
    section = session.get(Section, a.section_id)
    if a.student_id == actor.id:
        section_student(session, actor, a.section_id)
        if not valid_sources(session, session.get(Question, a.question_id)):
            return {**attempt_view(a), "feedback": None}
    else:
        staff_access(session, actor, section.course_id, "analyze")
    return attempt_view(a)


@router.post("/attempts/{attempt_id}/appeal", status_code=202)
def appeal(attempt_id: str, session: Db, actor: Actor):
    a = session.scalar(select(Attempt).where(Attempt.id == attempt_id).with_for_update())
    if not a or a.student_id != actor.id:
        deny(404)
    section = section_student(session, actor, a.section_id)
    if (
        a.appealed
        or a.status not in ("graded", "held")
        or session.get(Question, a.question_id).kind != "essay"
    ):
        deny(409, "자동 재검토는 서술형 답안당 한 번 요청할 수 있어요.")
    a.appealed, a.status, a.correct, a.score = True, "pending", None, None
    # Do not grant graduation or erase the existing review after an appeal.
    job = Job(
        owner_id=actor.id, course_id=section.course_id, kind="grade", payload={"attempt_id": a.id}
    )
    session.add(job)
    session.commit()
    return {"job_id": job.id, "status": "pending"}


@router.get("/sections/{section_id}/analytics")
def analytics(section_id: str, session: Db, actor: Actor):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    staff_access(session, actor, section.course_id, "analyze")
    attempts = list(
        session.scalars(
            select(Attempt).where(Attempt.section_id == section_id).order_by(Attempt.created_at)
        )
    )
    enrollments = list(
        session.scalars(select(Enrollment).where(Enrollment.section_id == section_id))
    )
    students = {e.student_id for e in enrollments} | {a.student_id for a in attempts}
    concepts = list(session.scalars(select(Concept).where(Concept.course_id == section.course_id)))

    def counts(rows):
        valid = [a for a in rows if a.status == "graded" and a.independent]
        correct = sum(bool(a.correct) for a in valid)
        return {
            "participation": len(rows),
            "valid": len(valid),
            "correct": correct,
            "accuracy": round(100 * correct / len(valid), 1) if valid else None,
            "pending": sum(a.status in ("pending", "held") for a in rows),
        }

    return {
        "section_id": section_id,
        "summary": counts(attempts),
        "concepts": [
            {"id": c.id, "name": c.name, **counts([a for a in attempts if a.concept_id == c.id])}
            for c in concepts
        ],
        "students": [
            {
                "id": sid,
                "name": session.get(User, sid).display_name,
                **counts([a for a in attempts if a.student_id == sid]),
            }
            for sid in sorted(students)
        ],
    }


@router.get("/sections/{section_id}/my-learning")
def my_learning(section_id: str, session: Db, actor: Actor):
    from lerny.automatic import calendar_week, weekly_content

    section = section_student(session, actor, section_id)
    concepts = list(session.scalars(select(Concept).where(Concept.course_id == section.course_id)
                                   .order_by(Concept.created_at, Concept.id)))
    current_week = calendar_week(session, section) if section.progress_mode == "auto" else section.progress_week
    weekly = weekly_content(session, section.course_id)
    weeks_by_concept = {}
    for week, ids in weekly.items():
        for cid in ids:
            weeks_by_concept.setdefault(cid, set()).add(week)
    scope = {cid for week, ids in weekly.items() if week <= current_week for cid in ids} \
        if section.progress_mode == "auto" else set(section.progress)
    # Older manually authored questions may predate material concept extraction.
    unmapped = {concept.id for concept in concepts} - weeks_by_concept.keys()
    for question in session.scalars(select(Question).where(
        Question.course_id == section.course_id, Question.status == "active"
    )):
        if question.concept_id in unmapped and valid_sources(session, question):
            weeks_by_concept.setdefault(question.concept_id, set()).update({
                session.get(Material, session.get(MaterialVersion, session.get(Chunk, source["chunk_id"]).version_id).material_id).week
                for source in question.sources
            })
    ids = [concept.id for concept in concepts]
    ranked = select(Attempt.id, func.row_number().over(
        partition_by=Attempt.concept_id, order_by=(Attempt.created_at.desc(), Attempt.id.desc())
    ).label("position")).where(
        Attempt.student_id == actor.id, Attempt.concept_id.in_(ids),
        Attempt.status == "graded", Attempt.independent.is_(True)
    ).subquery()
    recent = {}
    for attempt, day in session.execute(select(Attempt, LearningSession.day)
        .join(ranked, ranked.c.id == Attempt.id)
        .join(LearningSession, LearningSession.id == Attempt.learning_session_id)
        .where(ranked.c.position <= 5).order_by(Attempt.created_at.desc(), Attempt.id.desc())):
        recent.setdefault(attempt.concept_id, []).append((attempt, day))
    reviews = {review.concept_id: review for review in session.scalars(select(Review).where(
        Review.student_id == actor.id, Review.concept_id.in_(ids)
    ))}
    items = []
    for concept in concepts:
        entries = recent.get(concept.id, [])
        rows = [attempt for attempt, _ in entries]
        success_days = {day for attempt, day in entries if attempt.correct}
        review = reviews.get(concept.id)
        items.append(
            {
                "id": concept.id,
                "concept": concept.name,
                "weeks": sorted(weeks_by_concept.get(concept.id, [])),
                "in_scope": concept.id in scope,
                "valid_recent": len(rows),
                "correct_recent": sum(bool(a.correct) for a in rows),
                "mastered": len(rows) == 5
                and sum(bool(a.correct) for a in rows) >= 4
                and len(success_days) >= 2,
                "review_due": review.due_on if review else None,
                "review_session_id": rows[0].learning_session_id if rows else None,
                "review_question_id": rows[0].question_id if rows else None,
            }
        )
    return {"items": items, "current_week": current_week, "today": today()}


@router.get("/sections/{section_id}/analytics.csv")
def analytics_csv(section_id: str, session: Db, actor: Actor):
    result = analytics(section_id, session, actor)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["학생", "참여", "유효 답안", "정답", "정답률", "대기·보류"])
    for student in result["students"]:
        name = student["name"]
        # Spreadsheet formulas must never be executable through a display name.
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow(
            [
                name,
                student["participation"],
                student["valid"],
                student["correct"],
                student["accuracy"],
                student["pending"],
            ]
        )
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="learning.csv"'},
    )


@router.get("/sections/{section_id}/students/{student_id}/learning")
def student_detail(
    section_id: str, student_id: str, session: Db, actor: Actor,
    date_from: date | None = None, date_to: date | None = None,
    concept_id: str | None = None,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200),
):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    staff_access(session, actor, section.course_id, "analyze")
    enrollment = session.scalar(
        select(Enrollment)
        .where(Enrollment.student_id == student_id, Enrollment.section_id == section_id)
        .limit(1)
    )
    if not enrollment:
        deny(404)
    if date_from and date_to and date_from > date_to:
        deny(422, "종료일은 시작일보다 같거나 늦어야 해요.")
    query = select(Attempt).where(
        Attempt.student_id == student_id, Attempt.section_id == section_id)
    # Match the Korea-time dates shown in the professor's answer list.
    korea = timezone(timedelta(hours=9))
    if date_from:
        query = query.where(Attempt.created_at >= datetime.combine(date_from, time.min, korea))
    if date_to:
        query = query.where(Attempt.created_at <= datetime.combine(date_to, time.max, korea))
    if concept_id:
        query = query.where(Attempt.concept_id == concept_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    attempts = session.scalars(query.order_by(Attempt.created_at.desc(), Attempt.id.desc())
                              .offset(offset).limit(limit))
    return {
        "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total,
        "items": [
            {
                **attempt_view(a),
                "answer": (
                    session.get(Question, a.question_id).options[int(a.answer)]
                    if session.get(Question, a.question_id).kind == "mcq"
                    else a.answer
                ),
                "question": session.get(Question, a.question_id).prompt,
                "concept": session.get(Concept, a.concept_id).name,
                "created_at": a.created_at,
            }
            for a in attempts
        ]
    }


@router.get("/courses/{course_id}/held-attempts")
def held_attempts(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id, "analyze")
    rows = session.scalars(
        select(Attempt)
        .join(Section, Attempt.section_id == Section.id)
        .where(Section.course_id == course_id, Attempt.status == "held")
        .order_by(Attempt.created_at)
        .limit(200)
    )
    return {
        "items": [
            {
                "id": a.id,
                "student": session.get(User, a.student_id).display_name,
                "question": session.get(Question, a.question_id).prompt,
                "answer": a.answer,
                "criteria": session.get(Question, a.question_id).solution["criteria"],
            }
            for a in rows
        ]
    }


class ManualGrade(Input):
    scores: list[Literal[0, 50, 100]] = Field(min_length=2, max_length=4)
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/attempts/{attempt_id}/resolve")
def resolve(attempt_id: str, body: ManualGrade, session: Db, actor: Actor):
    a = session.scalar(select(Attempt).where(Attempt.id == attempt_id).with_for_update())
    if not a:
        deny(404)
    section = session.get(Section, a.section_id)
    staff_access(session, actor, section.course_id, "analyze")
    staff_access(session, actor, section.course_id, "edit")
    q = session.get(Question, a.question_id)
    if a.status != "held" or len(body.scores) != len(q.solution["criteria"]):
        deny(409, "검토 보류 중인 답안과 채점 요소를 확인해 주세요.")
    a.status, a.score = "graded", sum(body.scores) // len(body.scores)
    a.correct = sum(body.scores) >= 70 * len(body.scores)
    a.feedback = {
        "message": "교수 검토가 완료됐어요.",
        "criteria": [
            {"criterion": criterion, "score": score}
            for criterion, score in zip(q.solution["criteria"], body.scores, strict=True)
        ],
    }
    apply_review(session, a)
    audit(session, actor, "attempt.resolve", a.id, {"reason": body.reason, "scores": body.scores})
    session.commit()
    return attempt_view(a)
