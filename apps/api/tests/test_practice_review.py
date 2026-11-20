"""Authenticated local PostgreSQL tests; never execute code or call a model."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from lerny.learning import today
from lerny.models import Enrollment, Material, PracticeAttempt, PracticeExercise, PracticeSession, User, uid
from test_identity_courses import login
from test_personal_pipeline import prepared


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["blank", "full"])
@pytest.mark.parametrize("use_hints", [False, True])
async def test_answer_requires_owned_final_submission_and_preserves_frozen_attempt(app_db, monkeypatch, kind, use_hints):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, sec, _, version, chunk, student = await prepared(client, db, monkeypatch)
        code = "n = 3\nprint(n + 1)"
        chunk.content = code
        ex = PracticeExercise(course_id=course["id"], version_id=version.id, concept_id=sec.progress[0],
            source_key="review-test", position=1, kind=kind, language="python", title="입력 처리",
            prompt="입력을 확인하세요.\n\n결과를 출력하세요.", template="n = 3\nprint([[빈칸]])" if kind == "blank" else "n = 3\n# 구현하세요",
            reference=code, blanks={"1": "n + 1"} if kind == "blank" else {},
            tests=[{"statement": "n = 3", "input": "n = 3", "expected": "4"},
                   {"statement": "n = 3", "input": "n = 7289", "expected": "7290"}],
            sources=[{"chunk_id": chunk.id, "quote": code}], status="ready")
        db.add(ex); db.flush()
        from publication_fixtures import published
        published(db, course["id"])
        progress_url = "/api/v1/my/practice-progress"
        assert (await client.get(progress_url)).json()["items"] == []
        assert not db.scalar(select(PracticeSession.id).where(PracticeSession.student_id == student.id))
        plan = PracticeSession(student_id=student.id, section_id=sec.id, day=today(), week=1, exercise_ids=[ex.id])
        old = PracticeSession(student_id=student.id, section_id=sec.id, day=today()-timedelta(days=1), week=1, exercise_ids=[ex.id])
        db.add_all([plan, old]); db.flush()
        db.add(PracticeAttempt(student_id=student.id, section_id=sec.id, practice_session_id=old.id,
            exercise_id=ex.id, source=code, status="held", independent=True))
        db.commit()
        assert (await client.get(progress_url, params={"session_id": old.id})).json()["items"] == []
        current_progress = {"session_id": plan.id}
        first = (await client.get(progress_url, params=current_progress)).json()["items"]
        assert first[0]["remaining_exercise_ids"] == [ex.id]
        base = f"/api/v1/sections/{sec.id}/practice"
        async def help(kind, **extra):
            return await client.post(base + "/help", json={"exercise_id": ex.id, "kind": kind, **extra})
        assert not (await help("state")).json()["can_view_answer"]  # previous day's attempt is not today's submission
        invalid = await client.post(base + "/submit", json={"exercise_id": ex.id, "source": "[[빈칸]]"})
        assert invalid.status_code == 422
        if use_hints:
            for step in range(1, (4 if kind == "full" else 3) + 1):
                result = (await help("hint", step=step)).json()
                assert not result["can_view_answer"] and "answers" not in result
        assert (await help("answer")).status_code == 409
        daily = (await client.post(base + "/daily")).json()["items"][0]
        assert not {"answers", "reference", "explanation", "tests"}.intersection(daily)
        assert daily["example_input"] == "n = 3" and "7289" not in str(daily)
        assert (await client.get(base + f"/attempts/{uid()}/explanation")).status_code == 404
        submitted = await client.post(base + "/submit", headers={"Idempotency-Key": "review-final"},
            json={"exercise_id": ex.id, "source": code})
        assert submitted.status_code == 202, submitted.text
        aid = submitted.json()["id"]
        visible = {"section_id": sec.id, "session_id": plan.id, "total": 1, "submitted": 1}
        assert (await client.get(progress_url)).json()["items"] == [visible]
        assert (await client.get(progress_url, params=current_progress)).json()["items"] == [
            {**visible, "remaining_exercise_ids": []}]
        scoped = await client.get(base + "/attempts", params={"plan_id": plan.id})
        assert [item["id"] for item in scoped.json()["items"]] == [aid]
        archive = f"/api/v1/sections/{sec.id}/my-practice"
        oldest = (await client.get(archive, params={"order": "asc", "limit": 1})).json()
        assert oldest["total"] == 2
        assert oldest["items"][0]["id"] != aid
        assert submitted.json()["independent"] == (not use_hints)
        answer = (await help("answer")).json()
        assert answer["can_view_answer"] and answer["explanation"]["reference"] == code
        assert "7289" not in str(answer)
        db.expire_all()
        assert db.get(PracticeAttempt, aid).independent == (not use_hints)
        review_url = base + f"/attempts/{aid}/explanation"
        assert (await client.get(review_url)).json()["reference"] == code
        other = db.scalar(select(User).where(User.login_id == "student2"))
        db.add(Enrollment(student_id=other.id, course_id=course["id"], section_id=sec.id, status="active"))
        db.commit()
        await login(client, "student2")
        assert (await client.get(progress_url, params=current_progress)).json()["items"] == []
        assert (await client.get(progress_url)).json()["items"] == []
        assert (await client.get(base + "/attempts", params={"plan_id": plan.id})).json()["items"] == []
        assert (await client.get(review_url)).status_code == 404
        await login(client, "student1")
        db.get(Material, version.material_id).visibility = "private"; db.commit()
        assert (await client.get(progress_url)).json()["items"] == [{**visible, "total": 0, "submitted": 0}]
        assert (await help("answer")).status_code == 404
        assert (await client.get(review_url)).status_code == 404
