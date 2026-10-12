from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from lerny.learning import today
from lerny.models import (
    Attempt, Concept, Course, Enrollment, LearningSession, Material, MaterialVersion,
    Question, Section, User, now,
)
from test_identity_courses import login
from test_learning import seed

pytestmark = pytest.mark.asyncio


async def test_concept_navigation_keeps_weeks_scope_and_recent_evidence_separate(app_db):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, section, material = await seed(client, db)
        question = db.scalar(select(Question).where(Question.course_id == course["id"]))
        future = Concept(course_id=course["id"], name="미래 개념")
        db.add(future)
        db.flush()
        for week, visibility in [(12, "public"), (99, "private")]:
            source = Material(course_id=course["id"], title="test source", kind="lecture", week=week, visibility=visibility)
            db.add(source)
            db.flush()
            version = MaterialVersion(material_id=source.id, version_no=1, filename="test.txt",
                object_key="test.txt", sha256="0" * 64, status="ready", concept_ids=[future.id])
            db.add(version)
            db.flush()
            source.active_version_id = version.id
        student = db.scalar(select(User).where(User.login_id == "student1"))
        for index in range(7):
            learning = LearningSession(student_id=student.id, section_id=section["id"],
                day=today() - timedelta(days=index), question_ids=[question.id])
            db.add(learning)
            db.flush()
            db.add(Attempt(student_id=student.id, section_id=section["id"],
                learning_session_id=learning.id, question_id=question.id, concept_id=question.concept_id,
                answer="0", status="graded", independent=True, correct=index in (0, 1, 3, 4),
                created_at=now() - timedelta(days=index)))
        model = db.get(Section, section["id"])
        model.progress_week = 2
        db.commit()
        path = f"/api/v1/sections/{section['id']}/my-learning"
        result = (await client.get(path)).json()
        items = {item["id"]: item for item in result["items"]}
        current = items[question.concept_id]
        assert current["weeks"] == [1]  # Source-linked legacy questions still have a week.
        assert current["in_scope"] is True
        assert current["valid_recent"] == 5 and current["correct_recent"] == 4
        assert current["mastered"] is True
        assert items[future.id]["weeks"] == [12]  # No private week metadata.
        assert items[future.id]["in_scope"] is False
        assert result["current_week"] == 2
        model.progress, model.progress_week = [future.id], 12
        db.commit()
        items = {item["id"]: item for item in (await client.get(path)).json()["items"]}
        assert items[future.id]["in_scope"] is True
        assert items[question.concept_id]["in_scope"] is False
        # Automatic schedules compute today's scope, not stale section.progress.
        model.progress_mode = "auto"
        model.week_schedule = [{"week": 1, "date": today().isoformat()},
            {"week": 12, "date": (today() + timedelta(days=7)).isoformat()}]
        db.get(MaterialVersion, material.active_version_id).concept_ids = [question.concept_id]
        db.commit()
        items = {item["id"]: item for item in (await client.get(path)).json()["items"]}
        assert items[question.concept_id]["in_scope"] is True
        assert items[future.id]["in_scope"] is False
        await login(client, "student2")
        assert (await client.get(path)).status_code == 404


async def test_history_pages_past_100_records_without_mixing_students_or_sections(app_db):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, section, _ = await seed(client, db)
        student = db.scalar(select(User).where(User.login_id == "student1"))
        other = db.scalar(select(User).where(User.login_id == "student2"))
        original = db.get(Course, course["id"])
        other_course = Course(term_id=original.term_id, lead_teacher_id=original.lead_teacher_id,
            title="다른 강의", teaching_language="python")
        db.add(other_course)
        db.flush()
        second = Section(course_id=other_course.id, title="다른 분반")
        db.add(second)
        db.flush()
        db.add(Enrollment(student_id=student.id, course_id=other_course.id, section_id=second.id, status="active"))
        for index in range(105):
            db.add(LearningSession(student_id=student.id, section_id=section["id"],
                day=today() - timedelta(days=index), question_ids=[]))
        db.add(LearningSession(student_id=student.id, section_id=second.id, day=today(), question_ids=[]))
        db.add(LearningSession(student_id=other.id, section_id=section["id"], day=today(), question_ids=[]))
        db.commit()
        path = "/api/v1/my/learning-sessions"
        filters = {"section_id": section["id"], "limit": 10}
        first = (await client.get(path, params=filters)).json()
        last = (await client.get(path, params={**filters, "offset": 100})).json()
        assert first["total"] == last["total"] == 105
        assert len(first["items"]) == 10 and first["has_more"] is True
        assert len(last["items"]) == 5 and last["has_more"] is False
        assert not ({row["id"] for row in first["items"]} & {row["id"] for row in last["items"]})
        assert last["items"][-1]["day"] == (today() - timedelta(days=104)).isoformat()
        bounded = (await client.get(path, params={**filters,
            "date_from": (today() - timedelta(days=2)).isoformat(), "date_to": today().isoformat()})).json()
        assert bounded["total"] == 3
        assert (await client.get(path, params={"date_from": "2026-10-13", "date_to": "2026-10-12"})).status_code == 422
        assert (await client.get(path, params={"offset": -1})).status_code == 422
        assert (await client.get(path, params={"limit": 101})).status_code == 422
        await login(client, "student2")
        assert (await client.get(path, params=filters)).status_code == 404
