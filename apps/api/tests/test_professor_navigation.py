from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from lerny.learning import today
from lerny.models import Attempt, Concept, LearningSession, Question, Section, User
from test_identity_courses import login
from test_learning import seed

pytestmark = pytest.mark.asyncio


async def test_professor_answers_page_past_200_and_filter_korea_dates_without_leaks(app_db):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, section, _ = await seed(client, db)
        student = db.scalar(select(User).where(User.login_id == "student1"))
        other = db.scalar(select(User).where(User.login_id == "student2"))
        question = db.scalar(select(Question).where(Question.course_id == course["id"], Question.kind == "mcq"))
        concept = Concept(course_id=course["id"], name="다른 개념")
        second = Section(course_id=course["id"], title="다른 분반")
        db.add_all([concept, second])
        db.flush()
        extra = Question(course_id=course["id"], concept_id=concept.id, kind="essay", prompt="다른 개념 설명", options=[], solution={}, sources=question.sources)
        db.add(extra)
        db.flush()
        # Same timestamp tests stable ID tie breaking across every page.
        instant = datetime(2026, 10, 11, 15, tzinfo=timezone.utc)  # Oct 12 midnight in Korea.
        expected = set()
        for index in range(205):
            learning = LearningSession(student_id=student.id, section_id=section["id"],
                day=today() - timedelta(days=index), question_ids=[question.id, extra.id])
            db.add(learning)
            db.flush()
            attempt = Attempt(student_id=student.id, section_id=section["id"], learning_session_id=learning.id,
                question_id=question.id, concept_id=question.concept_id, answer="0", status="graded",
                correct=True, created_at=instant)
            db.add(attempt)
            db.flush()
            expected.add(attempt.id)
        # Adjacent date boundary and other concept must be independently filterable.
        db.add(Attempt(student_id=student.id, section_id=section["id"], learning_session_id=learning.id,
            question_id=extra.id, concept_id=concept.id, answer="서술 답안 전문", status="held",
            created_at=instant - timedelta(microseconds=1)))
        for user_id, section_id in [(other.id, section["id"]), (student.id, second.id)]:
            isolated = LearningSession(student_id=user_id, section_id=section_id, day=today(), question_ids=[question.id])
            db.add(isolated)
            db.flush()
            db.add(Attempt(student_id=user_id, section_id=section_id, learning_session_id=isolated.id,
                question_id=question.id, concept_id=question.concept_id, answer="1", created_at=instant))
        db.commit()
        route = f"/api/v1/sections/{section['id']}/students/{student.id}/learning"
        assert (await client.get(route)).status_code == 404  # Student cannot access professor detail.
        await login(client, "teacher2")
        assert (await client.get(route)).status_code == 404
        await login(client, "teacher1")
        baseline = (await client.get(route)).json()
        assert len(baseline["items"]) == 200 and baseline["total"] == 206
        seen = []
        for offset in range(0, 206, 50):
            result = (await client.get(route, params={"limit": 50, "offset": offset})).json()
            assert result["total"] == 206
            assert result["has_more"] == (offset + 50 < 206)
            seen.extend(item["id"] for item in result["items"])
        assert len(set(seen)) == len(seen) == 206
        assert expected <= set(seen)
        dates = {"date_from": "2026-10-12", "date_to": "2026-10-12"}
        filtered = (await client.get(route, params=dates)).json()
        assert filtered["total"] == 205
        assert filtered["items"][0]["answer"] == "선입선출"  # Preserve display answer, not choice index.
        concept_only = (await client.get(route, params={"concept_id": concept.id})).json()
        assert concept_only["total"] == 1
        assert concept_only["items"][0]["answer"] == "서술 답안 전문"
        assert (await client.get(route, params={**dates, "concept_id": concept.id})).json()["total"] == 0
        assert (await client.get(route, params={"offset": 999})).json()["items"] == []
        for params in [{"offset": -1}, {"limit": 201}, {"date_from": "2026-10-13", "date_to": "2026-10-12"}]:
            assert (await client.get(route, params=params)).status_code == 422
        assert (await client.get(f"/api/v1/sections/{second.id}/students/{student.id}/learning")).status_code == 404
