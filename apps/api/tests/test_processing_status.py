from datetime import timedelta

import httpx
import pytest
from lerny.models import Job, User, now
from sqlalchemy import select
from test_identity_courses import login, setup_course
from test_materials import upload


@pytest.mark.asyncio
async def test_processing_current_work_is_per_concept_and_history_is_retained(app_db):
    app, db = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        item = (await upload(c, course["id"])).json()
        owner = db.scalar(select(User).where(User.login_id == "teacher1"))
        started = now()
        records = []
        for i, (kind, status, concept) in enumerate(
            [
                ("embed", "failed", None),
                ("embed", "waiting_ai", None),
                ("questions", "failed", "a"),
                ("questions", "succeeded", "a"),
                ("questions", "failed", "b"),
            ]
        ):
            records.append(
                Job(
                    owner_id=owner.id,
                    course_id=course["id"],
                    kind=kind,
                    status=status,
                    created_at=started + timedelta(seconds=i),
                    payload={
                        "source_version_id": item["version_id"],
                        "concept_id": concept,
                        "private": "must-not-leak",
                    },
                    error_code="LEGACY_BACKFILL_DEFERRED" if status == "waiting_ai" else None,
                )
            )
        db.add_all(records)
        db.commit()
        response = await c.get(f"/api/v1/courses/{course['id']}/processing")
        assert response.status_code == 200
        material = response.json()["items"][0]
        assert material["version_id"] == item["version_id"]
        by_id = {j["id"]: j for j in material["jobs"]}
        assert [by_id[j.id]["is_current"] for j in records] == [False, True, False, True, True]
        assert not by_id[records[0].id]["retryable"]
        assert by_id[records[4].id]["retryable"]
        assert "must-not-leak" not in response.text and '"payload"' not in response.text
        await login(c, "student1")
        assert (await c.get(f"/api/v1/courses/{course['id']}/processing")).status_code in {403, 404}
        await login(c, "teacher2")
        assert (await c.get(f"/api/v1/courses/{course['id']}/processing")).status_code in {403, 404}
