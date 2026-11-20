from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from lerny import personalized, practice, video_worker, worker
from lerny.config import settings
from lerny.learning import today
from lerny.models import (Attempt, Chunk, ConceptVideo, Enrollment, Job,
    LearningSession, MaterialVersion, PracticeAttempt, Question, Section, User, now)
from test_identity_courses import login
from test_learning import seed

pytestmark = pytest.mark.asyncio


async def prepared(client, session, monkeypatch):
    course, section, material = await seed(client, session)
    monkeypatch.setattr(settings(), "automatic_learning_enabled", True)
    sec = session.get(Section, section["id"])
    sec.progress_mode, sec.progress_week = "manual", 1
    sec.week_schedule = [{"week": 1, "date": today().isoformat()}]
    version = session.get(MaterialVersion, material.active_version_id)
    version.concept_ids = list(sec.progress)
    chunk = session.scalar(select(Chunk).where(Chunk.version_id == version.id))
    actor = session.scalar(select(User).where(User.login_id == "student1"))
    template=session.scalar(select(Question).where(Question.course_id==course["id"],Question.kind=="mcq"))
    for i in range(2):
        session.add(Question(course_id=course["id"],concept_id=template.concept_id,generation_id=template.generation_id,
            kind="mcq",prompt=f"추가 검토 문항 {i}",options=template.options,solution=template.solution,sources=template.sources))
    session.commit()
    return course, sec, material, version, chunk, actor


def generator(monkeypatch, chunk, material, version):
    monkeypatch.setattr("lerny.retrieval.search_public", lambda *a, **k: [(chunk, material, version)])
    def model(prompt, schema):
        if "questions" in schema.get("properties", {}):
            import json
            data = json.loads(prompt.split("\n", 1)[1])
            return {"questions": [{"concept_id": cid, "category": "principle",
                "question": f"{i + 1}번 문항에서 큐의 원소 처리 순서는 무엇인가요?",
                "options": ["선입선출", "후입선출", "크기순", "무작위"], "answer_index": 0,
                "explanation": "먼저 넣은 원소를 먼저 꺼냅니다.", "source_id": chunk.id,
                "quote": chunk.content} for i, cid in enumerate(data["plan"]["concept_slots"])]}
        if "correct_options" in schema.get("properties", {}):
            return {"correct_options": ["선입선출"]}
        return {"supported": True, "unambiguous": True, "answer_correct": True}
    monkeypatch.setattr(worker, "model_json", model)


async def test_daily_four_owned_frozen_and_help_audited(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, material, version, chunk, actor = await prepared(c, session, monkeypatch)
        route = f"/api/v1/sections/{sec.id}/daily"
        def no_model(*a,**k): raise AssertionError("Daily assignment cannot create unseen questions")
        monkeypatch.setattr(worker,"model_json",no_model)
        ready=(await c.post(route)).json()
        assert ready["target_count"]==4 and ready["status"]=="ready"
        assert (await c.post(route)).json()["id"]==ready["id"]
        assert len(ready["items"])==4
        assert not any("solution" in q or "correct_option" in q for q in ready["items"])
        assert all(session.get(Question,q["id"]).student_id is None for q in ready["items"])
        qid = ready["items"][0]["id"]
        path = f"/api/v1/learning-sessions/{ready['id']}/questions/{qid}"
        assert (await c.post(path + "/help", json={})).status_code == 200
        response = await c.post(path + "/submit", headers={"Idempotency-Key": "new-one"}, json={"answer": "0"})
        assert response.status_code == 202, response.text
        assert session.get(Attempt, response.json()["attempt_id"]).independent is False
        other = session.scalar(select(User).where(User.login_id == "student2"))
        session.add(Enrollment(student_id=other.id, course_id=course["id"], section_id=sec.id, status="active"))
        session.commit()
        await login(c, "student2")
        assert (await c.post(path + "/help", json={})).status_code == 404
        other_plan = (await c.post(route)).json()
        assert other_plan["id"] != ready["id"]
        assert len(other_plan["items"]) == 4
        material.visibility = "private"
        session.commit()
        await login(c, "student1")
        assert all(q["status"] == "unavailable" for q in (await c.post(route)).json()["items"])


async def test_review_starts_day_four_from_own_wrong_answers(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        _, sec, _, _, _, actor = await prepared(c, session, monkeypatch)
        q = session.scalar(select(Question))
        learning = LearningSession(student_id=actor.id, section_id=sec.id, day=today(), question_ids=[q.id])
        session.add(learning); session.flush()
        session.add(Attempt(student_id=actor.id, section_id=sec.id, learning_session_id=learning.id,
            question_id=q.id, concept_id=q.concept_id, answer="1", status="graded", correct=False, independent=True))
        session.flush()
        day3 = personalized.learning_context(session, sec, actor.id, today()+timedelta(days=2))
        day4 = personalized.learning_context(session, sec, actor.id, today()+timedelta(days=3))
        other = session.scalar(select(User).where(User.login_id == "student2"))
        clean = personalized.learning_context(session, sec, other.id, today()+timedelta(days=3))
        assert not day3["review_enabled"] and not day3["review_concepts"]
        assert day4["review_enabled"] and day4["review_concepts"] == [q.concept_id]
        assert day4["previous"][0]["answer"] == "1" and len(day4["concept_slots"]) == 4
        assert clean["previous"] == [] and clean["review_concepts"] == []


async def test_uncertain_paid_submission_never_claimed_twice(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, _, version, _, actor = await prepared(c, session, monkeypatch)
        row = ConceptVideo(course_id=course["id"], version_id=version.id, concept_id=sec.progress[0],
            owner_id=actor.id, position=1, title="큐", status="submitting", lease_until=now()-timedelta(seconds=1))
        session.add(row); session.commit()
        assert video_worker.claim(session) is None
        assert row.status == "needs_attention"
        assert video_worker.claim(session) is None
        calls = []
        monkeypatch.setattr(video_worker, "update", lambda item, **kw: calls.append(kw))
        monkeypatch.setattr(video_worker, "persist_prepared", lambda item, body: True)
        from lerny.heygen_slides import compile_studio
        request = compile_studio("큐", ["synthetic-card"], ["먼저 넣은 값을 먼저 꺼냅니다."])
        # Exercise the uncertain-response branch with a mocked transport only.
        monkeypatch.setattr(video_worker.settings(), "heygen_rendering_enabled", True)
        def timeout(request):
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            video_worker.process({"action": "submit", "request": request}, client)
        assert calls == [{"status": "needs_attention", "error_code": "SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT"}]


async def test_practice_uses_source_and_hidden_inputs_and_isolates_logs(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, sec, material, version, chunk, actor = await prepared(c, session, monkeypatch)
        code = "numbers = [1, 2]\ntotal = sum(numbers)\nprint(total)"
        chunk.content = code
        monkeypatch.setattr(worker, "model_json", lambda *args: {"programs": [{"source_id": chunk.id,
            "concept_id": sec.progress[0], "code": code, "title": "합 구하기", "prompt": "숫자의 합을 계산해 출력하세요.",
            "input_statement": "numbers = [1, 2]", "variants": ["numbers = [3, 4]", "numbers = [0, 0]"],
            "blank_lines": [2], "full_template": "numbers = [1, 2]\n# 구현하세요"}]})
        # No source is executed by this test, including reference programs.
        def sandbox(language, source):
            output = "3" if "[1, 2]" in source else "7" if "[3, 4]" in source else "0"
            if "print(3)" in source: output = "3"
            return {"language": language, "status": "ok", "events": [{"stdout": output}], "clipped": False}
        monkeypatch.setattr("lerny.tracing.service.run_in_sandbox", sandbox)
        job = Job(owner_id=actor.id, course_id=course["id"], kind="practice_prepare", payload={"source_version_id": version.id})
        session.add(job); session.flush()
        assert len(practice.prepare(session, job)["exercise_ids"]) == 2
        assert practice.prepare(session, job)["exercise_ids"] == []
        from publication_fixtures import published
        published(session,course["id"])
        session.commit()
        base = f"/api/v1/sections/{sec.id}/practice"
        daily = (await c.post(base + "/daily")).json()
        assert len(daily["items"]) == 2
        exercise = daily["items"][0]
        assert all(k not in exercise for k in ("reference", "answers", "tests"))
        submitted = await c.post(base + "/submit", headers={"Idempotency-Key":"practice-1"},
            json={"exercise_id": exercise["id"], "source":"numbers = [1, 2]\nprint(3)"})
        assert submitted.status_code == 202, submitted.text
        a = session.get(PracticeAttempt, submitted.json()["id"])
        result = practice.grade(session, session.get(Job, a.job_id)); session.commit()
        assert result["correct"] is False and result["feedback"]["passed"] == 1
        assert (await c.post(base + "/help", json={"exercise_id":exercise["id"],"kind":"answer"})).status_code == 200
        await login(c, "student2")
        assert (await c.get(base + "/attempts")).status_code == 404
        await login(c, "student1")
        material.visibility = "private"; session.commit()
        assert (await c.get(base + "/attempts")).json()["items"][0]["exercise"] is None


async def test_practice_probe_rejects_added_execution():
    with pytest.raises(ValueError):
        practice.input_variants("n = 1", ["n = 2; open('x')", "n = 3"])


async def test_practice_keeps_safe_negative_and_variable_length_array_probes():
    result=practice.input_variants("numbers = [3, 1, 4]", ["numbers = [0]",
        "numbers = [10, -5, 20]", "numbers=[-10,-20,-30]", "numbers=[100,200,300]"])
    assert len(result)==5 and "numbers = [0]" in result
    assert "numbers=[-10,-20,-30]" in result
    with pytest.raises(ValueError):
        practice.input_variants("n = 1", ["n = 2+3", "n = 4-5"])


async def test_practice_accepts_uploaded_variable_length_examples_without_new_logic():
    values = ["numbers = [2, 5]", "numbers = [0, 0]", "numbers = [-2, 1]"]
    assert practice.input_variants("numbers = [3, 1, 4]", values) == ["numbers = [3, 1, 4]", *values]
    for changed in ("numbers = [2+3, 4]", "numbers = [1, 2]; print(9)",
                    "other = [1, 2]", "numbers = [x for x in range(3)]", "numbers = (1, 2)"):
        with pytest.raises(ValueError):
            practice.input_variants("numbers = [3, 1, 4]", [changed, "numbers = [0, 0]"])
