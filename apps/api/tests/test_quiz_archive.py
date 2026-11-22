from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from lerny.learning import today
from lerny.models import (Attempt, ContentGeneration, Enrollment, Job, LearningSession, PracticeAttempt,
                          PracticeExercise, PracticeSession, TheoryRetake, User, now)
from test_identity_courses import login
from test_personal_pipeline import prepared


@pytest.mark.asyncio
@pytest.mark.parametrize("personalized", [True, False])
async def test_current_week_only_preserves_existing_assignment_on_same_day_publication(app_db, monkeypatch, personalized):
    from lerny.config import settings
    from lerny.models import Chunk, DailyPlan, Material, MaterialVersion, Question
    from publication_fixtures import published

    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, section, material, _, _, student = await prepared(client, db, monkeypatch)
        monkeypatch.setattr(settings(), "automatic_learning_enabled", personalized)
        day = today()
        section.progress_mode = "auto"
        section.week_schedule = [{"week": 4, "date": (day - timedelta(weeks=8)).isoformat()},
                                 {"week": 12, "date": day.isoformat()}]
        older = db.scalar(select(ContentGeneration).where(ContentGeneration.course_id == course["id"]))
        older.week = material.week = 4
        question = db.scalar(select(Question).where(Question.generation_id == older.id, Question.kind == "mcq"))
        stale = LearningSession(student_id=student.id, section_id=section.id, day=day, question_ids=[question.id])
        db.add(stale)
        db.add(DailyPlan(student_id=student.id, section_id=section.id, day=day, week=4, day_index=7, context={}))
        db.flush()
        db.add(Attempt(student_id=student.id, section_id=section.id, learning_session_id=stale.id,
                       concept_id=question.concept_id, question_id=question.id, answer="0", status="graded", correct=True))
        db.commit()
        base = f"/api/v1/sections/{section.id}"
        progress = "/api/v1/my/learning-sessions?today_only=true"
        archive = base + "/quiz-archive/4/days"
        empty = (await client.post(base + "/daily")).json()
        assert empty["week"] == 12 and empty["items"] == [] and "12주차" in empty["message"]
        assert (await client.get(progress)).json()["total"] == 0
        assert (await client.get(archive)).json()["days"][-1]["session_id"] == stale.id

        # Publishing later on the same KST date must keep the already-submitted answer.
        current = Material(course_id=course["id"], title="12주차", kind="lecture", week=12, visibility="public")
        db.add(current)
        db.flush()
        version = MaterialVersion(material_id=current.id, version_no=1, filename="new.txt", object_key="new",
                                  sha256="1" * 64, status="ready")
        db.add(version)
        db.flush()
        current.active_version_id = version.id
        chunk = Chunk(version_id=version.id, content="12주차 근거 문장", locator={"page": 1})
        db.add(chunk)
        db.flush()
        fresh = Question(course_id=course["id"], concept_id=question.concept_id, kind="mcq", prompt="12주차 문제",
                         options=question.options, solution=question.solution, sources=[{"chunk_id": chunk.id, "quote": chunk.content}])
        db.add(fresh)
        published(db, course["id"], week=12, concept_ids=[question.concept_id])
        db.commit()
        assert (await client.get(progress)).json()["items"] == []
        active = (await client.post(base + "/daily")).json()
        assert active["week"] == 12 and [q["id"] for q in active["items"]] == [fresh.id]
        assert (await client.post(base + "/daily")).json() == active
        records = (await client.get(progress)).json()
        assert records["total"] == 1 and records["items"][0]["answered"] == 0
        saved = (await client.post(archive + "/7", params={"session_id": stale.id})).json()
        assert saved["items"][0]["submitted_answer"] == question.options[0] and saved["items"][0]["explanation"]
        assert (await client.get(archive)).json()["days"][-1]["submitted"] == 1
        assert (await client.get("/api/v1/my/learning-sessions")).json()["total"] == 2
        # Historical mixed assignments can carry the current plan week.
        mixed = db.get(LearningSession, active["id"])
        mixed.question_ids = [fresh.id, question.id]
        db.commit()
        assert (await client.get(progress)).json()["items"] == []
        replacement = (await client.post(base + "/daily")).json()
        assert replacement["id"] != mixed.id and [q["id"] for q in replacement["items"]] == [fresh.id]
        archived = (await client.post(base + "/quiz-archive/12/days/1", params={"session_id": mixed.id})).json()
        assert [q["id"] for q in archived["items"]] == [fresh.id, question.id]


@pytest.mark.asyncio
async def test_archive_opens_all_exercises_and_first_answers_are_read_only(app_db, monkeypatch):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        course, section, material, version, chunk, student = await prepared(c, db, monkeypatch)
        start = today() - timedelta(weeks=9)
        section.week_schedule = [{"week": 3, "date": start.isoformat()}, {"week": 12, "date": today().isoformat()}]
        section.progress_week = 12
        material.week = 3
        generation = db.scalar(select(ContentGeneration).where(ContentGeneration.course_id == course["id"]))
        generation.week = 3
        exercises = []
        for i in range(4):
            exercise = PracticeExercise(course_id=course["id"], generation_id=generation.id, version_id=version.id,
                source_key=f"source-{i}", position=i, kind="full" if i == 3 else "blank", language="python", title="실습",
                prompt="빈칸을 채우세요.", template="print([[빈칸]])", reference="print(1)", blanks={"1": "1"},
                tests=[{"statement": "n=1", "input": "n=1", "expected": "1"}],
                sources=[{"chunk_id": chunk.id, "quote": chunk.content}], status="ready")
            exercises.append(exercise)
            db.add(exercise)
        full = PracticeExercise(course_id=course["id"], generation_id=generation.id, version_id=version.id,
            source_key=exercises[0].source_key, position=0, kind="full", language="python", title="실습",
            prompt="직접 구현하세요.", template="# 구현하세요.", reference="print(1)",
            tests=exercises[0].tests, sources=exercises[0].sources, status="ready")
        db.add(full)
        db.flush()
        previous = PracticeSession(student_id=student.id, section_id=section.id, week=3, day=start,
                                   exercise_ids=[exercises[0].id, full.id])
        db.add(previous)
        db.flush()
        db.add(PracticeAttempt(student_id=student.id, section_id=section.id, exercise_id=exercises[0].id,
                               practice_session_id=previous.id, status="graded", source="print(1)", correct=True,
                               created_at=now() - timedelta(days=1)))
        # Both submissions predate the group rule. Keep the originals and review the first.
        db.add(PracticeAttempt(student_id=student.id, section_id=section.id, exercise_id=full.id,
                               practice_session_id=previous.id, status="graded", source="print(2)", correct=False))
        db.commit()
        api = f"/api/v1/sections/{section.id}"
        archive = api + "/quiz-archive"
        index = (await c.get(archive)).json()
        assert index["current_week"] == 12 and len(index["weeks"]) == 15
        assert index["weeks"][2] == {"week": 3, "theory": True, "practice": 4}
        assert not index["weeks"][12]["theory"]
        days = (await c.get(archive + "/3/days")).json()["days"]
        assert [d["index"] for d in days] == list(range(1, 8))
        assert all(d["submitted"] == 0 and d["total"] > 0 for d in days)
        assert not db.scalar(select(LearningSession.id))
        opened = (await c.post(archive + "/3/days/2")).json()
        assert opened["day"] == (start + timedelta(days=1)).isoformat()
        assert (await c.post(archive + "/3/days/2")).json()["id"] == opened["id"]
        question = next(q for q in opened["items"] if q["kind"] == "mcq")
        route = f"/api/v1/learning-sessions/{opened['id']}/questions/{question['id']}"
        assert (await c.post(route + "/submit", json={"answer": "1"},
                             headers={"Idempotency-Key": "original"})).status_code == 202
        assert (await c.post(route + "/retake", json={"answer": "0"})).status_code == 409
        assert (await c.post(route + "/submit", json={"answer": "0"},
                             headers={"Idempotency-Key": "different-key"})).status_code == 409
        saved = (await c.post(archive + "/3/days/2", params={"session_id": opened["id"]})).json()
        row = next(q for q in saved["items"] if q["id"] == question["id"])
        assert row["attempt"]["correct"] is False
        assert row["submitted_answer"] == question["options"][1] and row["explanation"]
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1
        assigned = LearningSession(student_id=student.id, section_id=section.id,
                                   day=start, question_ids=[question["id"]])
        db.add(assigned)
        db.commit()
        repeated = (await c.post(archive + "/3/days/1", params={"session_id": assigned.id})).json()
        assert repeated["items"][0]["attempt"] == row["attempt"]
        assert (await c.post(f"/api/v1/learning-sessions/{assigned.id}/questions/{question['id']}/submit",
                             json={"answer": "0"}, headers={"Idempotency-Key": "another-day"})).status_code == 409
        assert (await c.get(archive + "/3/days")).json()["days"][1]["submitted"] == 1
        assert (await c.post(archive + "/13/days/1")).status_code == 404
        assert (await c.post(archive + "/3/days/7", params={"session_id": opened["id"]})).status_code == 404
        weekly = (await c.post(archive + "/3/practice")).json()
        assert [x["id"] for x in weekly["items"]] == [e.id for e in exercises]
        assert [set(p["variants"]) for p in weekly["items"]] == [{"blank", "full"}, {"blank"}, {"blank"}, {"full"}]
        assert weekly["items"][0]["submitted_exercise_id"] == exercises[0].id
        assert weekly["items"][0]["attempt"]["source"] == "print(1)"
        assert (await c.post(archive + "/3/practice")).json()["id"] == weekly["id"]
        progress = "/api/v1/my/practice-progress"
        assert (await c.get(progress)).json()["items"] == []
        assert (await c.get(progress, params={"session_id": weekly["id"]})).json()["items"][0]["submitted"] == 1
        body = {"exercise_id": exercises[0].id, "plan_id": weekly["id"]}
        assert (await c.post(api + "/practice/help", json={**body, "kind": "answer"})).status_code == 200
        assert (await c.post(api + "/practice/submit", headers={"Idempotency-Key": "archive-practice"},
                             json={**body, "source": "print(2)"})).status_code == 409
        history = (await c.get(api + "/practice/attempts", params={"plan_id": weekly["id"]})).json()["items"]
        assert [a["source"] for a in history] == ["print(2)", "print(1)"]
        grouped = (await c.get(api + "/practice/attempts", params={"plan_id": weekly["id"], "by_exercise": True})).json()
        assert [a["source"] for a in grouped["items"]] == ["print(1)"]
        other = db.scalar(select(User).where(User.login_id == "student2"))
        db.add(Enrollment(student_id=other.id, course_id=course["id"], section_id=section.id, status="active"))
        db.commit()
        await login(c, "student2")
        assert (await c.post(archive + "/3/days/2", params={"session_id": opened["id"]})).status_code == 404
        assert (await c.post(route + "/retake", json={"answer": "0"})).status_code == 404
        assert (await c.post(api + "/practice/help", json={**body, "kind": "answer"})).status_code == 404
        assert (await c.get(api + "/practice/attempts", params={"plan_id": weekly["id"]})).json()["items"] == []
        await login(c, "student1")
        material.visibility = "private"
        db.commit()
        assert (await c.post(archive + "/3/practice")).json()["items"] == []
        assert (await c.post(archive + "/3/days/4")).status_code == 404
        assert (await c.post(route + "/retake", json={"answer": "0"})).status_code == 409
        assert db.scalar(select(func.count()).select_from(TheoryRetake)) == 0


@pytest.mark.asyncio
async def test_essay_only_enqueues_first_submission(app_db, monkeypatch):
    from test_learning import seed

    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        _, section, _ = await seed(c, db, legacy_session=True)
        daily = (await c.post(f"/api/v1/sections/{section['id']}/daily")).json()
        question = next(q for q in daily["items"] if q["kind"] == "essay")
        path = f"/api/v1/learning-sessions/{daily['id']}/questions/{question['id']}"
        first = await c.post(path + "/submit", json={"answer": "첫 답안"}, headers={"Idempotency-Key": "first"})
        retry = await c.post(path + "/retake", json={"answer": "다시 쓴 답안"}, headers={"Idempotency-Key": "retry"})
        assert first.status_code == 202 and retry.status_code == 409
        original = db.get(Attempt, first.json()["attempt_id"])
        assert original.status == "pending" and original.answer == "첫 답안"
        assert len(list(db.scalars(select(Job).where(Job.kind == "grade")))) == 1
        assert not db.scalar(select(TheoryRetake.id))
