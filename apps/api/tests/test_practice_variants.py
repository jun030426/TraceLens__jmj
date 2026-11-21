"""Exercise both entry points with separate PostgreSQL transactions per HTTP request."""
import asyncio
import hashlib
import json
from threading import Barrier

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lerny import practice
from lerny.models import (ContentGeneration, Enrollment, Job, LearningCompletion, PracticeAttempt,
                          PracticeExercise, User)
from test_cloud import cloud_db  # noqa: F401
from test_identity_courses import login
from test_personal_pipeline import prepared


@pytest.mark.asyncio
async def test_variants_share_submission_across_plans_and_weeks(cloud_db, monkeypatch, record_property):
    app, engine, _ = cloud_db
    code = "n = 3\nprint(n + 1)"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            course, section, material, version, chunk, _ = await prepared(c, db, monkeypatch)
            generation = db.scalar(select(ContentGeneration).where(ContentGeneration.course_id == course["id"]))
            section.progress_week = material.week = generation.week = 3
            chunk.content = code
            tests = [{"statement": "n = 3", "input": "n = 3", "expected": "4"},
                     {"statement": "n = 3", "input": "n = 7", "expected": "8"}]
            for kind, template in [("blank", "n = 3\n[[빈칸]]"), ("full", "n = 3\n# 여기에 구현하세요.")]:
                db.add(PracticeExercise(course_id=course["id"], version_id=version.id, generation_id=generation.id,
                    source_key=hashlib.sha256(code.encode()).hexdigest(), position=1, kind=kind, language="python",
                    title="다음 정수 출력하기", prompt="주어진 정수보다 1 큰 수를 출력하세요.", template=template,
                    reference=code, blanks={"1": "print(n + 1)"} if kind == "blank" else {}, tests=tests,
                    sources=[{"chunk_id": chunk.id, "quote": code}], status="ready"))
            db.commit()
            base = f"/api/v1/sections/{section.id}"
            daily = base + "/practice/daily"
            archive = base + "/quiz-archive/3/practice"
            submit = base + "/practice/submit"
            progress = "/api/v1/my/practice-progress"
            today_plan = (await c.post(daily)).json()
            weekly = (await c.post(archive)).json()
            assert weekly["id"] != today_plan["id"] and weekly["items"] == today_plan["items"]
            problem, = weekly["items"]
            blank = problem["variants"]["blank"]["exercise_id"]
            full = problem["variants"]["full"]["exercise_id"]
            assert blank != full and problem["submitted_exercise_id"] is None
            assert problem["variants"]["blank"]["template"] != problem["variants"]["full"]["template"]
            assert (await c.get(base + "/quiz-archive")).json()["weeks"][2]["practice"] == 1
            hint = await c.post(base + "/practice/help", json={"exercise_id": blank, "kind": "hint", "step": 1})
            assert hint.status_code == 200
            bodies = [{"exercise_id": blank, "source": code},
                      {"exercise_id": full, "plan_id": weekly["id"], "source": code}]
            # Both requests pass assignment checks before either acquires the submission lock.
            barrier = Barrier(2, timeout=10)
            assigned = practice.assigned
            def simultaneous(*args):
                result = assigned(*args)
                barrier.wait()
                return result
            with monkeypatch.context() as concurrent:
                concurrent.setattr(practice, "assigned", simultaneous)
                results = await asyncio.gather(*(c.post(submit, json=b,
                    headers={"Idempotency-Key": b["exercise_id"]}) for b in bodies))
            assert sorted(r.status_code for r in results) == [202, 409], [r.text for r in results]
            winner = next(r.json() for r in results if r.status_code == 202)
            assert not winner["independent"]
            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 1
            assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "practice_grade")) == 1
            selected = next(b for b in bodies if b["exercise_id"] == winner["exercise_id"])
            replay = await c.post(submit, json=selected, headers={"Idempotency-Key": selected["exercise_id"]})
            assert replay.json() == winner
            monkeypatch.setattr(practice, "output_of", lambda lang, src, **kw: "8" if "n = 7" in src else "4")
            assert practice.grade(db, db.get(Job, winner["job_id"]))["correct"]
            db.commit()
            assert db.scalar(select(func.count()).select_from(LearningCompletion)
                             .where(LearningCompletion.domain == "practice")) == 1
            for body in bodies:
                assert (await c.post(submit, json=body, headers={"Idempotency-Key": "new-" + body["exercise_id"]})).status_code == 409
            for route in (daily, archive):
                row, = (await c.post(route)).json()["items"]
                assert row["problem_id"] == problem["problem_id"]
                assert row["submitted_exercise_id"] == winner["exercise_id"]
                assert row["attempt"]["source"] == code and row["attempt"]["status"] == "graded"
            review = await c.get(base + f"/practice/attempts/{winner['id']}/explanation")
            assert review.json()["reference"] == code
            for eid in (blank, full):
                frozen = await c.post(base + "/practice/help", json={"exercise_id": eid, "kind": "hint", "step": 1})
                assert frozen.status_code == 409
            for plan in (weekly, today_plan):
                row, = (await c.get(progress, params={"session_id": plan["id"]})).json()["items"]
                assert (row["total"], row["submitted"], row["remaining_exercise_ids"]) == (1, 1, [])

            # In week 12, week 3 stays accessible in the archive. Today's assignment cannot absorb it.
            section.progress_week = 12
            other = db.scalar(select(User).where(User.login_id == "student2"))
            db.add(Enrollment(student_id=other.id, course_id=course["id"], section_id=section.id, status="active"))
            db.commit()
            assert (await c.post(daily)).json()["items"] == []
            assert (await c.get(progress)).json()["items"] == []
            await login(c, "student2")
            old = (await c.post(archive)).json()
            assert old["items"][0]["submitted_exercise_id"] is None
            record_property("archive_response", json.dumps(old, ensure_ascii=False))
            assert (await c.post(base + "/practice/help", json={"plan_id": old["id"], "exercise_id": blank,
                                 "kind": "hint", "step": 1})).status_code == 200
            for eid, expected_status in [(full, 202), (blank, 409)]:
                response = await c.post(submit, json={"plan_id": old["id"], "exercise_id": eid, "source": code},
                                        headers={"Idempotency-Key": "old-" + eid})
                assert response.status_code == expected_status
                if expected_status == 202:
                    assert response.json()["independent"] is False
            assert (await c.get(progress)).json()["items"] == []
            assert (await c.get(progress, params={"session_id": old["id"]})).json()["items"][0]["submitted"] == 1
