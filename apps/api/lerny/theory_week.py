"""Published theory questions and the original teaching slot of an assignment."""
from datetime import date

from sqlalchemy import func, select

from lerny.models import ContentGeneration, DailyPlan, Question
from lerny.weekly_content import sources_available


def question_bank(session, section, week, *, question_ids=None):
    from lerny.learning import valid_sources
    generations = list(session.scalars(select(ContentGeneration).where(
        ContentGeneration.course_id == section.course_id, ContentGeneration.week == week,
        ContentGeneration.status == "published")))
    published = [g.id for g in generations if sources_available(session, g)]
    if not published:
        return []
    query = select(Question).where(Question.course_id == section.course_id, Question.generation_id.in_(published),
                                   Question.student_id.is_(None), Question.status == "active")
    if question_ids is not None:
        query = query.where(Question.id.in_(question_ids))
    return [q for q in session.scalars(query.order_by(Question.created_at, Question.id))
            if valid_sources(session, q, week, require_published=False)]


def daily_plan(session, row):
    return session.scalar(select(DailyPlan).where(DailyPlan.student_id == row.student_id,
        DailyPlan.section_id == row.section_id, DailyPlan.day == row.day))


def is_current_assignment(session, row, plan, section, week):
    if row.archive_week is not None or not row.question_ids or (plan and plan.week != week):
        return False
    bank = question_bank(session, section, week, question_ids=row.question_ids)
    return set(row.question_ids) == {q.id for q in bank}


def assigned_slot(session, row, plan, starts):
    if row.archive_week is not None:
        return row.archive_week, row.archive_day_index
    if plan:
        return plan.week, plan.day_index
    # Sessions predating daily plans can also have been assigned weeks late.
    week = session.scalar(select(func.max(ContentGeneration.week)).select_from(Question)
        .join(ContentGeneration).where(Question.id.in_(row.question_ids)))
    if week is None:
        week = max((w for w, start in starts.items() if start <= row.day), default=0)
    return week, day_index(starts, week, row.day)


def week_starts(session, section):
    from lerny.automatic import section_schedule
    return {r["week"]: date.fromisoformat(r["date"]) for r in section_schedule(session, section)}


def day_index(starts, week, day):
    return max(1, min(7, (day - starts.get(week, day)).days + 1))
