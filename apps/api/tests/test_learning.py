from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from lerny.assessment import generate_job, grade_job, verify_choice
from lerny.learning import apply_review, today
from lerny.models import (
    Attempt,
    Chunk,
    Job,
    LearningSession,
    Material,
    MaterialVersion,
    Question,
    Review,
)
from sqlalchemy import select
from test_identity_courses import login, setup_course

pytestmark = pytest.mark.asyncio


async def test_generation_rejects_answer_key_that_disagrees_with_independent_solution(monkeypatch):
    question = SimpleNamespace(
        prompt="큐의 삭제 위치는?", options=["rear", "front", "middle", "random"], answer_index=0
    )
    monkeypatch.setattr("lerny.worker.model_json", lambda *args: {"correct_option": "front"})
    with pytest.raises(ValueError, match="ANSWER_KEY_MISMATCH"):
        verify_choice(question, [{"text": "dequeue는 front의 원소를 꺼낸다."}])
    question.answer_index = 1
    verify_choice(question, [{"text": "dequeue는 front의 원소를 꺼낸다."}])


async def seed(client, session):
    await login(client, "teacher1")
    course, section = await setup_course(client)
    concept = (
        await client.post(f"/api/v1/courses/{course['id']}/concepts", json={"name": "큐"})
    ).json()
    response = await client.put(
        f"/api/v1/sections/{section['id']}/progress",
        headers={"If-Match": "1"},
        json={"concept_ids": [concept["id"]]},
    )
    assert response.status_code == 200
    mat = Material(
        course_id=course["id"], title="lecture", kind="lecture", week=1, visibility="public"
    )
    session.add(mat)
    session.flush()
    version = MaterialVersion(
        material_id=mat.id,
        version_no=1,
        filename="x.txt",
        object_key="synthetic.txt",
        sha256="0" * 64,
        status="ready",
    )
    session.add(version)
    session.flush()
    mat.active_version_id = version.id
    chunk = Chunk(
        version_id=version.id,
        content="큐는 선입선출이다. 먼저 넣은 원소를 먼저 꺼낸다.",
        locator={"page": 1},
    )
    session.add(chunk)
    session.flush()
    for index, kind in enumerate(("mcq", "mcq", "essay")):
        session.add(
            Question(
                course_id=course["id"],
                concept_id=concept["id"],
                kind=kind,
                prompt=f"큐 설명 {index}",
                options=["선입선출", "후입선출", "정렬", "무작위"] if kind == "mcq" else [],
                solution={
                    "answer_index": 0,
                    "explanation": "선입선출이다.",
                    "criteria": ["먼저 넣은 원소", "먼저 꺼냄"] if kind == "essay" else [],
                },
                sources=[{"chunk_id": chunk.id, "quote": chunk.content}],
            )
        )
    session.commit()
    code = (await client.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()[
        "join_code"
    ]
    await login(client, "student1")
    assert (await client.post("/api/v1/enrollments", json={"join_code": code})).status_code == 201
    return course, section, mat


async def test_daily_persistent_answer_hidden_and_submission_idempotent(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        _, section, _ = await seed(c, session)
        route = f"/api/v1/sections/{section['id']}/daily"
        daily = (await c.post(route)).json()
        assert daily == (await c.post(route)).json()
        assert len(daily["items"]) == 3
        assert all("solution" not in q and "sources" not in q for q in daily["items"])
        q = daily["items"][0]
        submit = f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit"
        headers = {"Idempotency-Key": "answer-1"}
        first = await c.post(submit, headers=headers, json={"answer": "1"})
        assert first.status_code == 202, first.text
        assert first.json() == (await c.post(submit, headers=headers, json={"answer": "1"})).json()
        assert (
            await c.post(submit, headers={"Idempotency-Key": "another"}, json={"answer": "0"})
        ).status_code == 409
        review = session.scalar(select(Review))
        assert review.due_on == today() + timedelta(days=1)
        await login(c, "student2")
        assert (await c.get(f"/api/v1/attempts/{first.json()['attempt_id']}")).status_code == 404


async def test_source_revocation_blocks_question_and_statistics_access(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        course, section, material = await seed(c, session)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        assert (await c.get(f"/api/v1/sections/{section['id']}/analytics")).status_code == 404
        material.visibility = "private"
        session.commit()
        q = daily["items"][0]
        response = await c.post(
            f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
            headers={"Idempotency-Key": "r"},
            json={"answer": "0"},
        )
        assert response.status_code == 409
        redacted = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        assert all(q["status"] == "unavailable" and "options" not in q for q in redacted["items"])
        await login(c, "teacher2")
        assert (await c.get(f"/api/v1/courses/{course['id']}/questions")).status_code == 404


async def test_uncertain_essay_excluded_from_accuracy(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        _, section, _ = await seed(c, session)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        q = next(q for q in daily["items"] if q["kind"] == "essay")
        response = await c.post(
            f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
            headers={"Idempotency-Key": "essay"},
            json={"answer": "먼저 넣은 원소를 먼저 꺼냄"},
        )
        assert response.status_code == 202, response.text
        monkeypatch.setattr(
            "lerny.worker.model_json",
            lambda *args: {
                "certain": False,
                "criteria": {
                    "C1": {"score": 100, "answer_source_ids": ["A1"]},
                    "C2": {"score": 50, "answer_source_ids": ["A1"]},
                },
            },
        )
        result = grade_job(session, session.get(Job, response.json()["job_id"]))
        session.commit()
        assert result["status"] == "held"
        assert session.scalar(select(Review)) is None
        await login(c, "teacher1")
        summary = (await c.get(f"/api/v1/sections/{section['id']}/analytics")).json()["summary"]
        assert summary == {
            "participation": 1,
            "valid": 0,
            "correct": 0,
            "accuracy": None,
            "pending": 1,
        }


async def test_same_day_success_cannot_erase_wrong_review(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        _, section, _ = await seed(c, session)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        for index, q in enumerate(daily["items"][:2]):
            r = await c.post(
                f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
                headers={"Idempotency-Key": str(index)},
                json={"answer": "1" if index == 0 else "0"},
            )
            assert r.status_code == 202, r.text
        review = session.scalar(select(Review))
        assert review.stage == 0 and review.due_on == today() + timedelta(days=1)
        attempt = session.scalar(select(Attempt).where(Attempt.correct.is_(True)))
        learning = session.get(LearningSession, attempt.learning_session_id)
        learning.day = today() + timedelta(days=1)
        attempt.review_applied = False
        apply_review(session, attempt)
        assert review.stage == 1 and review.due_on == today() + timedelta(days=4)


async def test_held_resolution_and_csv_are_permission_checked(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        course, section, _ = await seed(c, session)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        q = next(q for q in daily["items"] if q["kind"] == "essay")
        result = (
            await c.post(
                f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
                headers={"Idempotency-Key": "held"},
                json={"answer": "선입선출"},
            )
        ).json()
        a = session.get(Attempt, result["attempt_id"])
        a.status = "held"
        session.commit()
        assert (await c.get(f"/api/v1/sections/{section['id']}/analytics.csv")).status_code == 404
        assert (
            await c.post(
                f"/api/v1/attempts/{a.id}/resolve",
                json={"scores": [100, 50], "reason": "교수 확인 테스트"},
            )
        ).status_code == 404
        await login(c, "teacher1")
        held = (await c.get(f"/api/v1/courses/{course['id']}/held-attempts")).json()
        assert len(held["items"]) == 1
        resolved = await c.post(
            f"/api/v1/attempts/{a.id}/resolve",
            json={"scores": [100, 50], "reason": "교수 확인 테스트"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["correct"] is True and resolved.json()["score"] == 75
        assert (
            await c.post(
                f"/api/v1/attempts/{a.id}/resolve",
                json={"scores": [0, 0], "reason": "중복 수정 금지"},
            )
        ).status_code == 409
        csv = await c.get(f"/api/v1/sections/{section['id']}/analytics.csv")
        assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")


async def test_generated_rubric_uses_canonical_public_sentences(app_db, monkeypatch):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        course, _, material = await seed(c, session)
        chunk = session.scalar(select(Chunk))
        version = session.get(MaterialVersion, chunk.version_id)
        existing = session.scalar(select(Question))
        monkeypatch.setattr(
            "lerny.assessment.search_public", lambda *args: [(chunk, material, version)]
        )
        monkeypatch.setattr("lerny.assessment.internal_validation_context", lambda *args: [])
        questions = [
            {
                "kind": kind,
                "prompt": "큐의 동작을 설명하는 문항입니다.",
                "options": ["a", "b", "c", "d"] if kind == "mcq" else [],
                "answer_index": 0,
                "explanation": "큐는 선입선출이다.",
                "criteria": ["S1", "S2"] if kind == "essay" else [],
                "sources": [{"chunk_id": "S1"}],
            }
            for kind in ("mcq", "mcq", "essay")
        ]
        monkeypatch.setattr(
            "lerny.worker.model_json",
            lambda prompt, schema: (
                {"questions": questions}
                if "questions" in schema.get("properties", {})
                else {"correct_option": "a"}
                if "correct_option" in schema.get("properties", {})
                else {"supported": True, "unambiguous": True, "answer_correct": True}
            ),
        )
        job = Job(
            course_id=course["id"],
            owner_id=existing.id,
            kind="questions",
            payload={"concept_id": existing.concept_id},
        )
        result = generate_job(session, job)
        essay = session.get(Question, result["question_ids"][-1])
        assert essay.solution["criteria"] == ["큐는 선입선출이다.", "먼저 넣은 원소를 먼저 꺼낸다."]
        assert all(criterion in chunk.content for criterion in essay.solution["criteria"])


async def test_history_is_read_only_and_session_results_are_owner_only(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        _, section, _ = await seed(c, session)
        assert (await c.get("/api/v1/my/learning-sessions")).json() == {
            "items": [], "total": 0, "offset": 0, "limit": 100, "has_more": False,
        }
        assert session.scalar(select(LearningSession)) is None
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        assert (await c.get(f"/api/v1/learning-sessions/{daily['id']}")).json() == daily
        history = (await c.get("/api/v1/my/learning-sessions")).json()["items"]
        assert len(history) == 1 and history[0]["submitted"] == 0
        await login(c, "student2")
        assert (await c.get(f"/api/v1/learning-sessions/{daily['id']}")).status_code == 404
        assert (await c.get("/api/v1/my/learning-sessions")).json()["items"] == []
        await login(c, "teacher1")
        assert (await c.get("/api/v1/my/learning-sessions")).status_code == 403


async def test_complete_bundle_counts_once_without_waiting_for_grading(app_db):
    from lerny.learning import record_completion
    from lerny.models import now
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        _, section, _ = await seed(c, session)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        assert not (await c.get("/api/v1/my/learning-streak")).json()["today_completed"]
        for i, q in enumerate(daily["items"]):
            response = await c.post(f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
                headers={"Idempotency-Key": f"complete-{i}"},
                json={"answer": "wrong explanation" if q["kind"] == "essay" else "1"})
            assert response.status_code == 202, response.text
            assert (await c.get("/api/v1/my/learning-streak")).json()["today_completed"] == (i == 2)
        owner = session.get(LearningSession, daily["id"]).student_id
        record_completion(session, owner, section["id"], "practice", "test-practice", now())
        record_completion(session, owner, section["id"], "practice", "test-practice", now())
        session.commit()
        summary = (await c.get("/api/v1/my/learning-streak")).json()
        assert summary["total_days"] == summary["current_streak"] == 1
        await login(c, "student2")
        assert (await c.get("/api/v1/my/learning-streak")).json()["total_days"] == 0


async def test_streak_calendar_boundaries():
    from datetime import date
    from lerny.learning import streak_summary
    day = date(2026, 10, 10)
    assert streak_summary([], day)["current_streak"] == 0
    assert streak_summary([day, day, day - timedelta(days=1)], day)["current_streak"] == 2
    assert streak_summary([day - timedelta(days=1)], day)["current_streak"] == 1
    assert streak_summary([day - timedelta(days=2)], day)["current_streak"] == 0
