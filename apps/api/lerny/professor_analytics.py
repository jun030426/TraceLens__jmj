"""Read-only professor analytics. Never used by student assignment or AI generation.

The two learning domains keep separate denominators. Chat topics are conservative
metadata associations, not an assessment of a student's understanding.
"""
import re
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import defer

from lerny.models import (Attempt, ChatMessage, Concept, Enrollment, LearningSession,
    Material, MaterialVersion, PracticeAttempt, PracticeExercise, Question, User, now)
from lerny.security import deny

KOREA = timezone(timedelta(hours=9))
MAX_RECORDS = 50000


def local_day(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(KOREA).date()


def window(date_from=None, date_to=None):
    end = date_to or local_day(now())
    start = date_from or end - timedelta(days=29)
    if start > end or (end - start).days > 365:
        deny(422, "조회 기간은 시작일 이후, 최대 366일로 선택해 주세요.")
    return start, end, datetime.combine(start, time.min, KOREA), datetime.combine(end + timedelta(days=1), time.min, KOREA)


def measured(attempt):
    return attempt.status == "graded" and attempt.correct is not None


def counts(attempts):
    valid = [a for a in attempts if measured(a) and a.independent]
    correct = sum(a.correct is True for a in valid)
    return {"submitted": len(attempts), "independent": len(valid), "correct": correct,
            "wrong": len(valid) - correct, "assisted": sum(measured(a) and not a.independent for a in attempts),
            "pending": sum(not measured(a) for a in attempts),
            "accuracy": round(100 * correct / len(valid), 1) if valid else None}


def theory_state(rows):
    # rows arrive newest first; dates are learning-session dates, not grading dates.
    valid = [row for row in rows if measured(row[0]) and row[0].independent]
    recent, previous = valid[:5], valid[5:10]
    correct = sum(row[0].correct is True for row in recent)
    days = len({row[2] for row in recent if row[0].correct})
    state = "no_data" if not rows else "insufficient" if len(recent) < 5 else (
        "mastered" if correct >= 4 and days >= 2 else "review" if correct < 4 else "learning")
    recent_accuracy = round(correct * 100 / len(recent), 1) if recent else None
    previous_accuracy = sum(row[0].correct is True for row in previous) * 20 if len(previous) == 5 else None
    return {"state": state, "sample": len(recent), "correct": correct, "success_days": days,
            "weakness": 100 - correct * 20 if len(recent) == 5 else None,
            "recent_accuracy": recent_accuracy,
            "trend_points": round(recent_accuracy - previous_accuracy, 1)
                if len(recent) == 5 and previous_accuracy is not None else None,
            "review": counts([a for a, review, _ in rows if review]),
            "evidence": [{"attempt_id": a.id, "question_id": a.question_id,
                "learning_session_id": a.learning_session_id, "correct": a.correct,
                "day": day, "created_at": a.created_at, "review": bool(review)}
                for a, review, day in recent]}


def concept_in_text(name, value):
    name = name.strip().casefold()
    if len(name) < 2:
        return False
    value = value.casefold()
    if re.fullmatch(r"[a-z0-9_ +.-]+", name):
        return bool(re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", value))
    return name in value


def bounded(session, query):
    rows = session.execute(query.limit(MAX_RECORDS + 1)).all()
    if len(rows) > MAX_RECORDS:
        deny(422, "조회 기록이 많아요. 기간을 줄이거나 학생 한 명을 선택해 주세요.")
    return rows


def load(session, section, start, end, *, student_id=None, concept_id=None):
    concepts = {c.id: c for c in session.scalars(select(Concept).where(Concept.course_id == section.course_id))}
    if concept_id and concept_id not in concepts:
        deny(404)
    roster = session.execute(select(User, Enrollment.status).join(Enrollment, Enrollment.student_id == User.id)
                            .where(Enrollment.section_id == section.id)).all()
    students = {}
    for user, status in roster:
        item = students.setdefault(user.id, {"id": user.id, "name": user.display_name, "active": False})
        item["active"] |= status == "active"
    if student_id and student_id not in students:
        deny(404)
    ids = [student_id] if student_id else list(students)
    theory_query = select(Attempt, Question.solution["review"].as_boolean(), LearningSession.day).join(
        Question, Attempt.question_id == Question.id).join(LearningSession, Attempt.learning_session_id == LearningSession.id).where(
        Attempt.section_id == section.id, Attempt.student_id.in_(ids), Question.course_id == section.course_id,
        Attempt.created_at >= start, Attempt.created_at < end).options(defer(Attempt.answer), defer(Attempt.feedback))
    practice_query = select(PracticeAttempt, PracticeExercise.concept_id, PracticeExercise.title, PracticeExercise.kind).join(
        PracticeExercise, PracticeAttempt.exercise_id == PracticeExercise.id).where(
        PracticeAttempt.section_id == section.id, PracticeAttempt.student_id.in_(ids),
        PracticeExercise.course_id == section.course_id,
        PracticeAttempt.created_at >= start, PracticeAttempt.created_at < end).options(
            defer(PracticeAttempt.source), defer(PracticeAttempt.feedback))
    if concept_id:
        theory_query = theory_query.where(Attempt.concept_id == concept_id)
        practice_query = practice_query.where(PracticeExercise.concept_id == concept_id)
    theory = bounded(session, theory_query.order_by(Attempt.created_at.desc(), Attempt.id.desc()))
    practice = bounded(session, practice_query.order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc()))
    chat_start = max(start, now() - timedelta(days=90))
    chat_rows = bounded(session, select(ChatMessage).where(ChatMessage.section_id == section.id,
        ChatMessage.student_id.in_(ids), ChatMessage.created_at >= chat_start, ChatMessage.created_at < end)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()))
    # Only current public source metadata is eligible for inferred chat topics.
    versions = {v.id: (v.material_id, [cid for cid in v.concept_ids or [] if cid in concepts])
        for v in session.scalars(select(MaterialVersion).join(Material, MaterialVersion.material_id == Material.id).where(
            Material.course_id == section.course_id, Material.visibility == "public", Material.internal_use == "none",
            Material.kind != "answer", Material.deleted.is_(False), Material.active_version_id == MaterialVersion.id,
            MaterialVersion.status == "ready"))}
    chats = []
    for (message,) in chat_rows:
        # Names are associated, not interpreted; do not claim a misconception from frequency.
        matched = {cid for cid, c in concepts.items() if concept_in_text(c.name, message.question)}
        methods = {cid: "name_match" for cid in matched}
        if not matched:
            cited = set()
            for citation in (message.answer or {}).get("citations", []):
                if not isinstance(citation, dict):
                    continue
                source = versions.get(citation.get("version_id"))
                if source and source[0] == citation.get("material_id"):
                    cited.update(source[1])
            # A multi-concept document is too ambiguous to attribute one question to all of it.
            if len(cited) == 1:
                methods = {next(iter(cited)): "single_source_concept"}
        if concept_id and concept_id not in methods:
            continue
        chats.append({"student_id": message.student_id, "created_at": message.created_at,
                      "topics": methods, "answered": bool(message.answer)})
    return {"students": students, "concepts": concepts, "theory": theory, "practice": practice, "chats": chats}


def chat_summary(chats, concepts):
    grouped = {}
    for message in chats:
        for cid, method in message["topics"].items():
            row = grouped.setdefault(cid, {"id": cid, "name": concepts[cid].name, "count": 0,
                "name_matches": 0, "source_inferences": 0, "last_at": message["created_at"]})
            row["count"] += 1
            row["name_matches" if method == "name_match" else "source_inferences"] += 1
    return {"count": len(chats), "answered": sum(c["answered"] for c in chats),
            "unclassified": sum(not c["topics"] for c in chats),
            "topics": sorted(grouped.values(), key=lambda r: (-r["count"], r["name"]))}


def summarize(data, student_id=None):
    theory = [r for r in data["theory"] if student_id is None or r[0].student_id == student_id]
    practice = [r for r in data["practice"] if student_id is None or r[0].student_id == student_id]
    chats = [r for r in data["chats"] if student_id is None or r["student_id"] == student_id]
    t_by, p_by = defaultdict(list), defaultdict(list)
    for row in theory:
        t_by[row[0].concept_id].append(row)
    for row in practice:
        if row[1]:
            p_by[row[1]].append(row[0])
    topics = chat_summary(chats, data["concepts"])
    topic_by = {r["id"]: r for r in topics["topics"]}
    concept_rows = []
    for cid in set(t_by) | set(p_by) | set(topic_by):
        if cid not in data["concepts"]:
            continue
        metric = counts([r[0] for r in t_by[cid]])
        concept_rows.append({"id": cid, "name": data["concepts"][cid].name,
            "theory": metric, "practice": counts(p_by[cid]), "learning": theory_state(t_by[cid]),
            "chat_count": topic_by.get(cid, {}).get("count", 0)})
    order = {"review": 0, "insufficient": 1, "learning": 2, "mastered": 3, "no_data": 4}
    concept_rows.sort(key=lambda c: (order[c["learning"]["state"]], -(c["learning"]["weakness"] or 0), c["name"]))
    dates = [r[0].created_at for r in theory + practice] + [c["created_at"] for c in chats]
    return {"theory": counts([r[0] for r in theory]), "practice_summary": counts([r[0] for r in practice]),
            "chat": topics, "concepts": concept_rows, "last_activity_at": max(dates) if dates else None}


def overview(data):
    by_student = {sid: {"students": {}, "concepts": data["concepts"], "theory": [], "practice": [], "chats": []}
                  for sid in data["students"]}
    for key in ("theory", "practice", "chats"):
        for row in data[key]:
            sid = row["student_id"] if key == "chats" else row[0].student_id
            by_student[sid][key].append(row)
    students = []
    concepts = defaultdict(lambda: {"review_students": 0, "insufficient_students": 0, "mastered_students": 0})
    for sid, student in data["students"].items():
        summary = summarize(by_student[sid])
        for item in summary["concepts"]:
            state = item["learning"]["state"]
            if state in {"review", "insufficient", "mastered"}:
                concepts[item["id"]][state + "_students"] += 1
        students.append({**student, **{k: summary[k] for k in ("theory", "practice_summary", "chat", "last_activity_at")},
                         # Compact per-student evidence from the same bulk query and calculation.
                         # No answers, code, chat text or additional per-student database calls.
                         "concept_signals": [{"id": c["id"], "name": c["name"],
                             **{key: c["learning"][key] for key in
                                ("state", "sample", "correct", "success_days", "weakness", "trend_points")}}
                             for c in summary["concepts"]],
                         "review_concepts": [c["name"] for c in summary["concepts"] if c["learning"]["state"] == "review"],
                         "insufficient_concepts": sum(c["learning"]["state"] == "insufficient" for c in summary["concepts"])})
    total = summarize(data)
    observed = {row["id"] for row in total["concepts"]}
    total["concepts"].extend({"id": cid, "name": concept.name, "theory": counts([]),
        "practice": counts([]), "chat_count": 0} for cid, concept in data["concepts"].items() if cid not in observed)
    # Never calculate one student's mastery by pooling different students' answers.
    total["concepts"] = [{k: v for k, v in row.items() if k != "learning"} | concepts[row["id"]]
                         for row in total["concepts"]]
    total["students"] = sorted(students, key=lambda s: (-len(s["review_concepts"]), s["name"], s["id"]))
    total["student_count"] = len(students)
    total["active_students"] = sum(s["active"] for s in students)
    total["participating_students"] = sum(s["last_activity_at"] is not None for s in students)
    return total
