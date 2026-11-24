"""Real local PostgreSQL + authenticated HTTP; no models or student code executed."""
import ast
import inspect

import httpx
import pytest
from sqlalchemy import select

from lerny.learning import today
from lerny.learning_signals import select_slots, weakness
from lerny.models import (Attempt, AuditEvent, ChatMessage, Course, Enrollment, Job,
    LearningSession, PracticeExercise, PracticeSession, Question, User, uid)
from lerny.team_engine import validate_short_narration
from rag_mvp.cloze_generator import ClozeGenerator
from quiz_mvp.generation import generate
from test_identity_courses import login
from test_personal_pipeline import prepared


@pytest.mark.asyncio
async def test_feedback_is_owned_persisted_idempotent_and_epoch_bound(app_db, monkeypatch):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, _, _, _, student = await prepared(c, db, monkeypatch)
        answer = ChatMessage(student_id=student.id, section_id=sec.id, thread_id=uid(), question="큐 설명",
            answer={"answer": "선입선출입니다."}, access_epoch=db.get(Course, course["id"]).access_epoch,
            learning_context={"concept_id": sec.progress[0], "mode": "theory"})
        db.add(answer); db.commit()
        route = f"/api/v1/sections/{sec.id}/chat/messages/{answer.id}/feedback"
        assert (await c.put(route, json={"value": "confused"})).status_code == 200
        saved = dict(answer.feedback)
        assert (await c.put(route, json={"value": "confused"})).status_code == 200
        assert answer.feedback == saved
        history = (await c.get(f"/api/v1/sections/{sec.id}/chat/history")).json()
        assert history["items"][0]["feedback"] == "confused"
        assert weakness(db, student.id, sec.id, sec.progress)[sec.progress[0]]["feedback"] == 65
        assert (await c.put(route, json={"value": "unknown"})).status_code == 200
        assert weakness(db, student.id, sec.id, sec.progress)[sec.progress[0]]["feedback"] == 80
        other = db.scalar(select(User).where(User.login_id == "student2"))
        db.add(Enrollment(student_id=other.id, course_id=course["id"], section_id=sec.id, status="active")); db.commit()
        await login(c, "student2")
        assert (await c.put(route, json={"value": "understood"})).status_code == 404
        assert (await c.put(route.replace(answer.id, uid()), json={"value": "understood"})).status_code == 404
        await login(c, "student1")
        db.get(Course, course["id"]).access_epoch += 1; db.commit()
        assert (await c.put(route, json={"value": "understood"})).status_code == 409
        assert weakness(db, student.id, sec.id, sec.progress)[sec.progress[0]]["feedback"] == 50


@pytest.mark.asyncio
async def test_progressive_hints_survive_reload_and_do_not_leak_answers(app_db, monkeypatch):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, _, version, chunk, student = await prepared(c, db, monkeypatch)
        code = "n = 3\nprint(n + 1)"
        chunk.content = code
        ex = PracticeExercise(course_id=course["id"], version_id=version.id, concept_id=sec.progress[0],
            source_key="handoff", position=1, kind="full", language="python", title="입력 처리",
            prompt="입력을 처리하세요.", template="n = 3\n# 구현하세요", reference=code, blanks={},
            tests=[{"statement": "n = 3", "input": "n = 3", "expected": "4"}],
            sources=[{"chunk_id": chunk.id, "quote": code}], status="ready")
        db.add(ex); db.flush()
        from publication_fixtures import published
        published(db,course["id"])
        plan = PracticeSession(student_id=student.id, section_id=sec.id, day=today(), week=1, exercise_ids=[ex.id])
        db.add(plan); db.commit()
        base = f"/api/v1/sections/{sec.id}"
        route = base + "/practice/help"
        async def help(kind, **extra):
            return await c.post(route, json={"exercise_id": ex.id, "kind": kind, **extra})
        assert (await help("answer")).status_code == 409
        assert (await help("hint", step=3)).status_code == 409
        assert (await help("hint", step=1)).status_code == 200
        assert (await help("hint", step=1)).json()["hints_used"] == 1
        assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "practice_help")))) == 1
        state = (await help("state")).json()
        assert state["max_hint_steps"] == 3 and "answers" not in state and not state["can_view_answer"]
        await help("hint", step=2)
        state = (await help("hint", step=3)).json()
        assert not state["can_view_answer"] and "answers" not in state
        assert (await help("hint", step=4)).status_code == 409
        assert (await help("answer")).status_code == 409
        submitted = await c.post(base + "/practice/submit", json={"exercise_id": ex.id, "source": code},
                                 headers={"Idempotency-Key": "hints-final"})
        assert submitted.status_code == 202, submitted.text
        # The copy text keeps the starter comment line and continues with the reference body below it.
        assert (await help("answer")).json()["answers"] == ["n = 3\n# 구현하세요\nprint(n + 1)"]
        response = await c.post(base + "/chat/messages", headers={"Idempotency-Key": "practice-context"},
            json={"message": "어디서 막혔나요?", "mode": "practice", "exercise_id": ex.id,
                  "practice_context": "학생 코드: n = 3"})
        assert response.status_code == 202, response.text
        message = db.get(ChatMessage, response.json()["resource_id"])
        assert message.learning_context["concept_id"] == sec.progress[0]
        assert message.learning_context["student_context"] == "학생 코드: n = 3"
        assert "reference" not in message.learning_context
        history = (await c.get(base + "/chat/history?mode=practice")).json()
        assert history["total"] == 1
        assert history["items"][0]["context"]["practice_title"] == ex.title
        assert "student_context" not in history["items"][0]["context"]
        assert (await c.get(base + "/chat/history?mode=theory")).json()["total"] == 0
        wrong = await c.post(base + "/chat/messages", headers={"Idempotency-Key": "unassigned"},
            json={"message": "질문", "mode": "practice", "exercise_id": uid()})
        assert wrong.status_code == 404
        # Changing the section's source authorization revokes hints and answers.
        from lerny.models import Material
        db.get(Material, version.material_id).visibility = "private"; db.commit()
        assert (await help("answer")).status_code == 404


@pytest.mark.asyncio
async def test_scoring_counts_first_independent_questions_and_keeps_four_slots(app_db, monkeypatch):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, _, version, chunk, student = await prepared(c, db, monkeypatch)
        cid = sec.progress[0]
        plan = LearningSession(student_id=student.id, section_id=sec.id, day=today(), question_ids=[])
        db.add(plan); db.flush()
        questions = []
        for i, difficulty in enumerate(["basic", "apply", "reason"]):
            q = Question(course_id=course["id"], concept_id=cid, kind="mcq", prompt=f"문제 {i}",
                         solution={"difficulty": difficulty}, sources=[{"chunk_id": chunk.id, "quote": chunk.content}])
            db.add(q); db.flush(); questions.append(q.id)
            db.add(Attempt(student_id=student.id, section_id=sec.id, learning_session_id=plan.id,
                question_id=q.id, concept_id=cid, answer="x", status="graded", correct=i > 0, independent=True))
        plan.question_ids = questions; db.flush()
        from datetime import timedelta
        retry_plan = LearningSession(student_id=student.id, section_id=sec.id, day=today() + timedelta(days=1), question_ids=[questions[0]])
        db.add(retry_plan); db.flush()
        # Retry cannot overwrite the first answer's signal.
        db.add(Attempt(student_id=student.id, section_id=sec.id, learning_session_id=retry_plan.id,
            question_id=questions[0], concept_id=cid, answer="fixed", status="graded", correct=True, independent=True))
        db.add(AuditEvent(actor_id=student.id, action="theory_help", target_id=plan.id, detail={"question_id": questions[1]}))
        db.flush()
        signal = weakness(db, student.id, sec.id, [cid])[cid]
        assert signal["samples"] == 3
        assert signal["quiz"] == pytest.approx(100 * 1.25 / 3)
        assert signal["hint"] == pytest.approx(100 / 3)
        assert signal["score"] == pytest.approx(43.33)
        slots, review = select_slots([cid], {cid: signal}, review_enabled=True)
        assert slots == [cid] * 4 and review == [cid]


def test_helpers_preserve_literals_require_isolation_and_validate_shorts():
    assert not ClozeGenerator.evaluate_blank_answer('"a b"', '"ab"')["correct"]
    assert ClozeGenerator.evaluate_blank_answer("x + 1", "x+1")["correct"]
    with pytest.raises(RuntimeError, match="ISOLATED_WORKER_REQUIRED"):
        ClozeGenerator.execute_practice_code("raise AssertionError('must never execute')")
    problem = ClozeGenerator.generate_full_coding_problem("def add(x):\n    return x + 1", target_func_name="add")
    ast.parse(problem["starter_code"])
    assert "return x + 1" not in problem["starter_code"]
    assert "generation_id" in inspect.signature(generate).parameters
    with pytest.raises(ValueError, match="SHORTS_NARRATION_LENGTH"):
        validate_short_narration(["짧음"], 50)
    validate_short_narration(["가" * 360], 50)


def test_day_four_mix_and_tutor_levels():
    from lerny.learning_signals import tutoring_instruction
    signals = {key: {"score": score, "wrong": 0} for key, score in [("a", 95), ("b", 80), ("c", 75), ("d", 10)]}
    slots, review = select_slots(["d"], signals, review_enabled=True)
    assert slots == ["a", "b", "c", "d"] and review == ["a", "b", "c"]
    assert select_slots(["d"], signals, review_enabled=False) == (["d"] * 4, [])
    assert "한 단계씩" in tutoring_instruction(70, "theory")
    assert "경계 조건" in tutoring_instruction(30, "theory")
    assert "완성 답안" in tutoring_instruction(50, "practice")
