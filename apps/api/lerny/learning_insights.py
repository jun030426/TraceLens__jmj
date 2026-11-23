"""Authorized professor evidence, own student history and course processing progress."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import defer, undefer

from lerny.models import Concept, DailyPlan, Job, Material, MaterialVersion, PracticeAttempt, PracticeExercise, Section
from lerny.security import Actor, Db, deny, staff_access
from lerny import professor_analytics as metrics

router = APIRouter(prefix="/api/v1")


@router.get("/sections/{section_id}/my-practice")
def my_practice(section_id: str, session: Db, actor: Actor, response: Response,
                order: Literal["asc", "desc"] = "desc",
                date_from: date | None = None, date_to: date | None = None,
                offset: int = Query(default=0, ge=0), limit: int = Query(default=10, ge=1, le=50)):
    from lerny.jobs import section_student
    from lerny.practice import current_source, student_exercise_template
    from lerny.practice_display import attempt_display
    section = section_student(session, actor, section_id)
    first, last, start, end = metrics.window(date_from, date_to)
    response.headers["Cache-Control"] = "private, no-store"
    query = select(PracticeAttempt, PracticeExercise.id).join(PracticeExercise,
        PracticeAttempt.exercise_id == PracticeExercise.id).where(
        PracticeAttempt.student_id == actor.id, PracticeAttempt.section_id == section_id,
        PracticeExercise.course_id == section.course_id,
        PracticeAttempt.created_at >= start, PracticeAttempt.created_at < end).options(
        defer(PracticeAttempt.source), defer(PracticeAttempt.feedback), defer(PracticeAttempt.submission_snapshot)).order_by(
        PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc())
    rows = metrics.bounded(session, query)
    if order == "asc":
        rows.reverse()
    page = rows[offset:offset + limit]
    attempts = {a.id: a for a in session.scalars(select(PracticeAttempt).where(
        PracticeAttempt.id.in_([a.id for a, _ in page])).options(
            undefer(PracticeAttempt.source), undefer(PracticeAttempt.feedback), undefer(PracticeAttempt.submission_snapshot)))}
    exercises = {e.id: e for e in session.scalars(select(PracticeExercise).where(
        PracticeExercise.id.in_([exercise_id for _, exercise_id in page])))}
    concepts = {c.id: c.name for c in session.scalars(select(Concept).where(Concept.course_id == section.course_id))}
    items = []
    for record, exercise_id in page:
        exercise = exercises[exercise_id]
        a = attempts[record.id]
        material = current_source(session, exercise)
        items.append({"id": a.id, "created_at": a.created_at, "status": a.status,
            "correct": a.correct, "independent": a.independent, "source": a.source,
            "feedback": attempt_display(a, exercise.kind, exercise.language)["feedback"] if material else None,
            "title": exercise.title if material else "공개 범위가 변경된 실습",
            "concept": concepts.get(exercise.concept_id, "개념 미지정") if material else "",
            "kind": exercise.kind, "language": exercise.language, "source_available": bool(material),
            "submission_snapshot": a.submission_snapshot if material else None,
            "template": student_exercise_template(exercise) if material and exercise.kind in {"blank", "cloze", "full"} else None})
    return {"date_from": first, "date_to": last, "summary": metrics.counts([a for a, _ in rows]),
            "items": items, "total": len(rows), "offset": offset, "limit": limit,
            "has_more": offset + len(items) < len(rows)}


def authorized_section(session, actor, section_id):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    staff_access(session, actor, section.course_id, "analyze")
    return section


@router.get("/sections/{section_id}/insights")
def section_insights(section_id: str, session: Db, actor: Actor, response: Response,
                     date_from: date | None = None, date_to: date | None = None):
    section = authorized_section(session, actor, section_id)
    first, last, start, end = metrics.window(date_from, date_to)
    data = metrics.load(session, section, start, end)
    response.headers["Cache-Control"] = "private, no-store"
    return {"section_id": section.id, "date_from": first, "date_to": last,
            "concept_options": [{"id": c.id, "name": c.name} for c in data["concepts"].values()],
            **metrics.overview(data)}


@router.get("/sections/{section_id}/students/{student_id}/insights")
def student_insights(section_id: str, student_id: str, session: Db, actor: Actor, response: Response,
                     date_from: date | None = None, date_to: date | None = None,
                     concept_id: str | None = None,
                     practice_offset: int = Query(default=0, ge=0),
                     practice_limit: int = Query(default=10, ge=1, le=50)):
    section = authorized_section(session, actor, section_id)
    first, last, start, end = metrics.window(date_from, date_to)
    data = metrics.load(session, section, start, end, student_id=student_id, concept_id=concept_id)
    summary = metrics.summarize(data, student_id)
    practice = data["practice"]
    page = practice[practice_offset:practice_offset + practice_limit]
    attempts = {a.id: a for a in session.scalars(select(PracticeAttempt).where(
        PracticeAttempt.id.in_([row[0].id for row in page])).options(
            undefer(PracticeAttempt.source), undefer(PracticeAttempt.feedback)))}
    plan = session.scalar(select(DailyPlan).where(DailyPlan.section_id == section_id,
        DailyPlan.student_id == student_id, DailyPlan.day >= first, DailyPlan.day <= last)
        .order_by(DailyPlan.day.desc()).limit(1))
    days = {}
    for kind in ("theory", "practice", "chats"):
        for row in data[kind]:
            moment = row["created_at"] if kind == "chats" else row[0].created_at
            key = metrics.local_day(moment).isoformat()
            entry = days.setdefault(key, {"day": key, "theory": 0, "practice": 0, "chat": 0})
            entry["chat" if kind == "chats" else kind] += 1
    response.headers["Cache-Control"] = "private, no-store"
    return {**summary, "student": data["students"][student_id], "date_from": first, "date_to": last,
        "concept_options": [{"id": c.id, "name": c.name} for c in data["concepts"].values()],
        # Compatibility fields now explicitly refer to THEORY, never a mixed-domain score.
        "concepts": [{**c, **c["theory"]} for c in summary["concepts"]],
        "theory_count": summary["theory"]["submitted"], "practice_count": len(practice),
        "timeline": sorted(days.values(), key=lambda r: r["day"], reverse=True),
        "latest_plan": {"day": plan.day, "week": plan.week, "day_index": plan.day_index,
                        "review_enabled": plan.context.get("review_enabled", False)} if plan else None,
        "practice_page": {"offset": practice_offset, "limit": practice_limit,
                          "total": len(practice), "has_more": practice_offset + len(page) < len(practice)},
        "practice": [{"id": a.id, "title": title, "kind": kind, "status": a.status, "correct": a.correct,
            "independent": a.independent, "created_at": a.created_at, "source": a.source,
            "feedback": a.feedback} for record, _, title, kind in page if (a := attempts[record.id])]}


@router.get("/courses/{course_id}/processing")
def processing(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id, "read")
    from lerny.media_progress import public_progress
    versions = {}
    for material in session.scalars(select(Material).where(Material.course_id == course_id, Material.deleted.is_(False))):
        version = session.scalar(select(MaterialVersion).where(MaterialVersion.material_id == material.id)
                                 .order_by(MaterialVersion.version_no.desc()).limit(1))
        if version:
            evidence=(version.extraction_report or {}).get('native_evidence')
            pipeline=evidence.get('pipeline','native') if isinstance(evidence,dict) else 'native'
            versions[version.id] = {"material_id": material.id, "title": material.title,
                "week": material.week, "version_id": version.id, "source_status": version.status, "jobs": [],
                "held_count":(version.extraction_report or {}).get('held_count',0),
                "extraction_pipeline":pipeline}
    for job in session.scalars(select(Job).where(Job.course_id == course_id,
            Job.kind.in_(["extract", "embed", "auto_concepts", "questions", "practice_prepare", "narration_lesson"]))
            .order_by(Job.created_at, Job.id)):
        vid = job.payload.get("source_version_id") or job.payload.get("version_id")
        if vid in versions:
            versions[vid]["jobs"].append({"id": job.id, "kind": job.kind, "status": job.status,
                "concept_id": job.payload.get("concept_id"), "created_at": job.created_at,
                "error_code": job.error_code, "retry_at": job.lease_until if job.status == "queued" and job.error_code else None,
                "retryable": job.owner_id == actor.id and job.status == "failed"
                    and job.kind != "narration_lesson", "result_status": (job.result or {}).get("status"), "progress": public_progress(job)})
    for item in versions.values():
        # Each concept has its own question/video work. An older failure must not
        # replace a later retry, nor hide another concept that still failed.
        latest = {(job["kind"], job["concept_id"]): job["id"] for job in item["jobs"]}
        for job in item["jobs"]:
            job["is_current"] = latest[(job["kind"], job["concept_id"])] == job["id"]
            job["retryable"] = job["retryable"] and job["is_current"]
    return {"items": sorted(versions.values(), key=lambda r: (r["week"], r["title"]))}
