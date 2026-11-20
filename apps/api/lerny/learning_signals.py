"""Handoff 40/20/40 scoring on authenticated, persisted learning events.

Practice execution and elapsed time deliberately have zero weight. Repeated or
assisted quiz answers cannot improve mastery; sparse evidence stays neutral.
"""
from sqlalchemy import select

from lerny.models import Attempt, AuditEvent, ChatMessage, Course, Section, LearningSession, Question


def weakness(session, student_id, section_id, concept_ids):
    ids = list(dict.fromkeys(concept_ids))
    rows = {cid: {"quiz": 50.0, "hint": 0.0, "feedback": 50.0,
                  "samples": 0, "helped": 0, "assigned": 0} for cid in ids}
    if not rows:
        return rows
    attempts = session.execute(select(Attempt, Question).join(Question, Attempt.question_id == Question.id)
        .where(Attempt.student_id == student_id, Attempt.section_id == section_id,
               Attempt.concept_id.in_(ids), Attempt.status == "graded")
        .order_by(Attempt.created_at, Attempt.id)).all()
    seen, scores = set(), {cid: [] for cid in ids}
    for attempt, question in attempts:
        if question.id in seen:
            continue
        seen.add(question.id)
        if not attempt.independent:
            continue
        weight = {"basic": 1.25, "apply": 1.0, "reason": .75}.get(question.solution.get("difficulty"), 1.0)
        scores[attempt.concept_id].append((bool(attempt.correct), weight))
    plans = list(session.scalars(select(LearningSession).where(
        LearningSession.student_id == student_id, LearningSession.section_id == section_id)))
    assigned = {qid for plan in plans for qid in plan.question_ids}
    questions = {q.id: q.concept_id for q in session.scalars(select(Question).where(
        Question.id.in_(assigned), Question.concept_id.in_(ids)))}
    helped = set()
    if plans:
        for event in session.scalars(select(AuditEvent).where(AuditEvent.actor_id == student_id,
                AuditEvent.action == "theory_help", AuditEvent.target_id.in_([p.id for p in plans]))):
            if event.detail.get("question_id") in questions:
                helped.add(event.detail["question_id"])
    for qid, cid in questions.items():
        rows[cid]["assigned"] += 1
        rows[cid]["helped"] += int(qid in helped)
    feedback_seen = set()
    section = session.get(Section, section_id)
    epoch = session.get(Course, section.course_id).access_epoch
    messages = session.scalars(select(ChatMessage).where(ChatMessage.student_id == student_id,
        ChatMessage.section_id == section_id, ChatMessage.access_epoch == epoch, ChatMessage.feedback.is_not(None)).order_by(
            ChatMessage.created_at.desc(), ChatMessage.id.desc()))
    # A single latest response per concept, never an accumulating penalty.
    for message in sorted(messages, key=lambda m: (m.feedback or {}).get("updated_at", ""), reverse=True):
        cid = (message.learning_context or {}).get("concept_id")
        if cid in rows and cid not in feedback_seen:
            feedback_seen.add(cid)
            rows[cid]["feedback"] = {"understood": 20, "confused": 80, "aborted": 65}.get(
                message.feedback.get("value"), 50)
    for cid, row in rows.items():
        samples = scores[cid]
        row["samples"] = len(samples)
        row["wrong"] = sum(not correct for correct, _ in samples)
        if len(samples) >= 3:
            row["quiz"] = 100 * sum(w for correct, w in samples if not correct) / sum(w for _, w in samples)
        row["hint"] = 100 * row["helped"] / row["assigned"] if row["assigned"] else 0
        row["score"] = round(.4 * row["quiz"] + .2 * row["hint"] + .4 * row["feedback"], 2)
        row["tier"] = "high" if row["score"] >= 70 else "mastery" if row["score"] <= 30 else "standard"
    return rows


def select_slots(new_ids, signals, *, review_enabled):
    new_ids = list(dict.fromkeys(new_ids))
    if not new_ids:
        raise ValueError("NO_ELIGIBLE_CONCEPTS")
    if not review_enabled:
        return [new_ids[i % len(new_ids)] for i in range(4)], []
    ranked = sorted((cid for cid, s in signals.items() if s["score"] > 40 or s["wrong"]),
                    key=lambda cid: (-signals[cid]["score"], cid))
    if not ranked:
        return [new_ids[i % len(new_ids)] for i in range(4)], []
    # Exactly four questions even when only one concept exists; distinct stems
    # remain enforced by generate_daily. Never duplicate IDs just to rank them.
    review = ranked[:3]
    stable = next((cid for cid in new_ids if cid not in review), new_ids[0])
    return [review[i % len(review)] for i in range(3)] + [stable], review


def tutoring_instruction(score, mode):
    level = ("용어를 풀어서 한 단계씩 설명하고 짧은 확인 질문을 덧붙인다." if score >= 70 else
             "핵심 원리와 경계 조건을 간결하게 설명하고 스스로 비교하도록 돕는다." if score <= 30 else
             "핵심 개념과 다음 확인 단계를 설명한다.")
    practice = (" 실습에서는 학생 코드의 오류 위치와 원인을 설명하되 완성 답안이나 빈칸의 정답을 제공하지 않는다. "
                "자료의 정답 코드를 그대로 인용하지 않는다.") if mode == "practice" else ""
    return level + practice
