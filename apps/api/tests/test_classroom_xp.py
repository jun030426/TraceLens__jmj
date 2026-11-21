from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from lerny.learning import today
from lerny.models import (
    Course, Enrollment, LearningCompletion, MaterialVersion, PracticeAttempt,
    PracticeExercise, PracticeSession, User,
)
from test_identity_courses import login
from test_learning import seed


async def seed_xp_classrooms(client, db):
    """One student's two courses, with different activity in each."""
    a, first, mat_a = await seed(client, db, legacy_session=True)
    b, second, mat_b = await seed(client, db)
    db.get(Course, b["id"]).title = "알고리즘"
    owner = db.scalar(select(User).where(User.login_id == "student1"))
    for course, room, material, sessions in [(a, first, mat_a, 2), (b, second, mat_b, 1)]:
        version = db.scalar(select(MaterialVersion).where(MaterialVersion.material_id == material.id))
        exercise = PracticeExercise(course_id=course["id"], version_id=version.id, source_key="xp",
            position=1, kind="full", language="python", title="예제", prompt="예제", template="",
            reference="", sources=[])
        db.add(exercise)
        db.flush()
        for i in range(sessions):
            plan = PracticeSession(student_id=owner.id, section_id=room["id"],
                day=today()-timedelta(days=i), week=1, exercise_ids=[exercise.id])
            db.add(plan)
            db.flush()
            db.add(PracticeAttempt(student_id=owner.id, section_id=room["id"],
                exercise_id=exercise.id, practice_session_id=plan.id, source="test"))
    # Only the first classroom has quiz completion and a three-day streak.
    for days_ago in (1, 2):
        db.add(LearningCompletion(student_id=owner.id, section_id=first["id"], domain="practice",
            source_id=f"complete-{days_ago}", day=today()-timedelta(days=days_ago)))
    db.commit()
    daily = (await client.post(f"/api/v1/sections/{first['id']}/daily")).json()
    assert daily["items"]
    for q in daily["items"]:
        result = await client.post(f"/api/v1/learning-sessions/{daily['id']}/questions/{q['id']}/submit",
            headers={"Idempotency-Key": f"xp-{q['id']}"}, json={"answer": "1" if q["kind"] == "mcq" else "예시"})
        assert result.status_code == 202, result.text
    return first["id"], second["id"]


@pytest.mark.asyncio
async def test_badge_activity_scoped_to_student_and_active_section(app_db):
    app, db = app_db
    paths = ["/api/v1/my/learning-sessions", "/api/v1/my/practice-submission-count", "/api/v1/my/learning-streak"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        first, second = await seed_xp_classrooms(c, db)

        async def counts(section_id):
            history, practice, streak = [await c.get(path, params={"section_id": section_id}) for path in paths]
            assert history.is_success and practice.is_success and streak.is_success
            completed = sum(r["total"] > 0 and r["submitted"] == r["total"] for r in history.json()["items"])
            return completed, practice.json()["submitted"], streak.json()["total_days"], streak.json()["current_streak"]

        assert await counts(first) == (1, 1, 3, 3)
        assert await counts(second) == (0, 1, 0, 0)
        assert (await c.get(paths[1])).json()["submitted"] == 2
        # Another student joins the same first classroom and has no access to the second.
        other = db.scalar(select(User).where(User.login_id == "student2"))
        enrollment = db.scalar(select(Enrollment).where(Enrollment.section_id == first))
        db.add(Enrollment(student_id=other.id, section_id=first, course_id=enrollment.course_id, status="active"))
        db.commit()
        await login(c, "student2")
        assert await counts(first) == (0, 0, 0, 0)
        for path in paths:
            assert (await c.get(path, params={"section_id": second})).status_code == 404
