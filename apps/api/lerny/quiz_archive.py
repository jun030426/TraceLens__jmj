"""Browse published weekly quizzes without generating questions."""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Path
from sqlalchemy import func, select

from lerny.automatic import calendar_week, section_schedule
from lerny.jobs import section_student
from lerny.learning import daily, five_daily_questions, lock_student, session_view, today, valid_sources
from lerny.models import (Attempt, Course, DailyPlan, LearningSession, PracticeExercise, PracticeSession,
                          Question)
from lerny.practice import exercise_view
from lerny.security import Actor, Db, deny
from lerny.weekly_content import published_generations

router = APIRouter(prefix="/api/v1")


def calendar(session, section):
    start = {r["week"]: date.fromisoformat(r["date"]) for r in section_schedule(session, section)}
    current = calendar_week(session, section, today()) if section.progress_mode == "auto" else section.progress_week
    return start, current or 0


def assignments(session, actor, section, starts):
    """Preserve the assigned week/day, including extra sessions from a long teaching week."""
    plans = {p.day: p for p in session.scalars(select(DailyPlan).where(
        DailyPlan.student_id == actor.id, DailyPlan.section_id == section.id))}
    by_week = defaultdict(list)
    for row in session.scalars(select(LearningSession).where(LearningSession.student_id == actor.id,
            LearningSession.section_id == section.id).order_by(LearningSession.day)):
        if plan := plans.get(row.day):
            week, index = plan.week, plan.day_index
        else:
            week = max((w for w, start in starts.items() if start <= row.day < start + timedelta(days=7)), default=0)
            if not week:
                continue
            index = (row.day - starts[week]).days + 1
        by_week[week].append((index, row))
    return by_week


def available_counts(session, model, generations, *filters):
    return dict(session.execute(select(model.generation_id, func.count()).where(
        model.generation_id.in_(generations), *filters).group_by(model.generation_id)).all())


@router.get("/sections/{section_id}/quiz-archive")
def weeks(section_id: str, session: Db, actor: Actor):
    section = section_student(session, actor, section_id)
    starts, current = calendar(session, section)
    records = assignments(session, actor, section, starts)
    generations = {g.id: g.week for g in published_generations(session, section.course_id) if g.week <= current}
    theory = available_counts(session, Question, generations, Question.status == "active", Question.student_id.is_(None))
    practice = available_counts(session, PracticeExercise, generations, PracticeExercise.status == "ready")
    by_week = {w: (theory.get(g, 0), practice.get(g, 0)) for g, w in generations.items()}
    items = []
    for week in range(1, 16):
        questions, exercises = by_week.get(week, (0, 0))
        items.append({"week": week, "theory": bool(records[week] or (questions and week in starts and starts[week] <= today())),
                      "practice": exercises})
    return {"course_title": session.get(Course, section.course_id).title, "section_title": section.title,
            "current_week": current, "weeks": items}


def question_bank(session, section, week):
    generations = [g.id for g in published_generations(session, section.course_id) if g.week == week]
    return [q for q in session.scalars(select(Question).where(Question.generation_id.in_(generations),
            Question.student_id.is_(None), Question.status == "active").order_by(Question.created_at, Question.id))
            if valid_sources(session, q, week)]


def day_questions(bank, index):
    by_position = defaultdict(list)
    for question in bank:
        by_position[question.solution.get("quiz_position")].append(question)
    rotated = []
    for position, group in by_position.items():
        step = 1 if position else 5
        start = ((index - 1) * step) % len(group)
        rotated.extend(group[start:] + group[:start])
    return five_daily_questions(rotated)


@router.get("/sections/{section_id}/quiz-archive/{week}/days")
def days(section_id: str, session: Db, actor: Actor, week: int = Path(ge=1, le=15)):
    section = section_student(session, actor, section_id)
    starts, current = calendar(session, section)
    records = assignments(session, actor, section, starts)
    own = records[week]
    occupied = {row.day for items in records.values() for _, row in items}
    answered = set(session.scalars(select(Attempt.question_id).where(
        Attempt.student_id == actor.id, Attempt.section_id == section.id).distinct()))
    bank = question_bank(session, section, week) if week <= current else []
    items = []
    for index in range(1, 8):
        rows = [row for day_index, row in own if day_index == index]
        if rows:
            for row in rows:
                items.append({"index": index, "date": row.day, "session_id": row.id,
                              "total": len(row.question_ids), "submitted": len(answered.intersection(row.question_ids))})
        else:
            when = starts[week] + timedelta(days=index - 1) if week in starts else None
            ready = when and when <= today() and when not in occupied
            ids = day_questions(bank, index) if ready else []
            items.append({"index": index, "date": when, "session_id": None,
                          "total": len(ids), "submitted": len(answered.intersection(ids))})
    return {"days": items}


@router.post("/sections/{section_id}/quiz-archive/{week}/days/{index}")
def open_day(section_id: str, session: Db, actor: Actor, week: int = Path(ge=1, le=15),
             index: int = Path(ge=1, le=7), session_id: str | None = None):
    section = section_student(session, actor, section_id)
    starts, current = calendar(session, section)
    if session_id:
        for slot, row in assignments(session, actor, section, starts)[week]:
            if slot == index and row.id == session_id:
                return session_view(session, row)
        deny(404)
    if week not in starts or week > current:
        deny(404)
    when = starts[week] + timedelta(days=index - 1)
    if when > today():
        deny(404)
    if when == today():
        # The daily endpoint acquires course and student locks in that order.
        return daily(section_id, session, actor)
    lock_student(session, actor.id)
    existing = session.scalar(select(LearningSession).where(LearningSession.student_id == actor.id,
        LearningSession.section_id == section_id, LearningSession.day == when))
    existing_plan = session.scalar(select(DailyPlan).where(DailyPlan.student_id == actor.id,
        DailyPlan.section_id == section_id, DailyPlan.day == when))
    if existing_plan and (existing_plan.week != week or existing_plan.day_index != index):
        deny(409, "이 날짜에는 다른 주차의 퀴즈가 배정돼 있어요.")
    if existing:
        return session_view(session, existing)
    chosen = day_questions(question_bank(session, section, week), index)
    if not chosen:
        deny(404, "이 날짜에 풀 수 있는 공개 문항이 없어요.")
    learning = LearningSession(student_id=actor.id, section_id=section_id, day=when, question_ids=chosen)
    session.add(learning)
    if not existing_plan:
        session.add(DailyPlan(student_id=actor.id, section_id=section_id, day=when,
                              week=week, day_index=index, context={"source": "archive"}))
    session.commit()
    return session_view(session, learning)


@router.post("/learning-sessions/{learning_id}/questions/{question_id}/retake")
def retake(learning_id: str, question_id: str, session: Db, actor: Actor):
    learning = session.get(LearningSession, learning_id)
    if not learning or learning.student_id != actor.id or question_id not in learning.question_ids:
        deny(404)
    section_student(session, actor, learning.section_id)
    deny(409, "문제는 한 번만 제출할 수 있어요. 내 답안과 해설을 확인해 주세요.")


@router.post("/sections/{section_id}/quiz-archive/{week}/practice")
def open_practice(section_id: str, session: Db, actor: Actor, week: int = Path(ge=1, le=15)):
    section = section_student(session, actor, section_id)
    _, current = calendar(session, section)
    if week > current:
        deny(404)
    generations = [g.id for g in published_generations(session, section.course_id) if g.week == week]
    lock_student(session, actor.id)
    items = [view for exercise in session.scalars(select(PracticeExercise).where(
        PracticeExercise.generation_id.in_(generations), PracticeExercise.status == "ready")
        .order_by(PracticeExercise.position, PracticeExercise.id)) if (view := exercise_view(session, exercise))]
    if not items:
        return {"week": week, "status": "empty", "items": [], "message": "이 주차에는 공개된 실습이 없어요."}
    ids = [item["id"] for item in items]
    plan = session.scalar(select(PracticeSession).where(PracticeSession.student_id == actor.id,
        PracticeSession.section_id == section_id, PracticeSession.week == week, PracticeSession.day.is_(None)))
    if not plan:
        plan = PracticeSession(student_id=actor.id, section_id=section_id, week=week, exercise_ids=ids)
        session.add(plan)
    elif plan.exercise_ids != ids:
        plan.exercise_ids = ids
    session.commit()
    return {"id": plan.id, "week": week, "items": items, "status": "ready"}
