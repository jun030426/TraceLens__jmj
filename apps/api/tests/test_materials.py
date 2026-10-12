import httpx
import pytest
from lerny import worker
from lerny.config import settings
from lerny.models import Job, Material, MaterialVersion
from test_identity_courses import login, setup_course

pytestmark = pytest.mark.asyncio


async def upload(c, course_id, visibility="public", content="큐는 선입선출 자료구조입니다."):
    return await c.post(
        f"/api/v1/courses/{course_id}/materials",
        data={"kind": "lecture", "week": "1", "visibility": visibility, "internal_use": "none"},
        files={"file": ("lecture.txt", content.encode(), "text/plain")},
    )


@pytest.fixture
def files_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "runtime_root", tmp_path)
    monkeypatch.setattr(worker, "embed", lambda texts: [[1.0, 0.0] for _ in texts])


async def test_public_private_and_revocation(app_db, files_root):
    app, _ = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, section = await setup_course(c)
        public = await upload(c, course["id"])
        private = await upload(c, course["id"], "private", "PRIVATE_SENTINEL")
        assert public.status_code == private.status_code == 201
        pubid, privid = public.json()["material_id"], private.json()["material_id"]
        code = (await c.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()[
            "join_code"
        ]
        await login(c, "student1")
        await c.post("/api/v1/enrollments", json={"join_code": code})
        items = (await c.get(f"/api/v1/courses/{course['id']}/materials")).json()["items"]
        assert [m["id"] for m in items] == [pubid]
        assert (await c.get(f"/api/v1/materials/{privid}/file")).status_code == 404
        assert (await c.get(f"/api/v1/materials/{pubid}/file")).status_code == 200
        await login(c, "teacher1")
        assert (
            await c.patch(
                f"/api/v1/materials/{pubid}/access",
                headers={"If-Match": "1"},
                json={"visibility": "private", "internal_use": "validation_grading"},
            )
        ).status_code == 200
        await login(c, "student1")
        assert (await c.get(f"/api/v1/materials/{pubid}/file")).status_code == 404


async def test_replacement_preserves_old_version_and_manual_text(app_db, files_root):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        created = (await upload(c, course["id"])).json()
        job = session.get(Job, created["processing_job_id"])
        worker.extract_job(session, job)
        session.commit()
        material = session.get(Material, created["material_id"])
        assert material.active_version_id == created["version_id"]
        edited = await c.put(
            f"/api/v1/materials/{material.id}/transcript",
            headers={"If-Match": "1"},
            json={"text": "교수가 수정한 큐의 설명입니다."},
        )
        assert edited.status_code == 200
        newjob = session.get(Job, edited.json()["job_id"])
        worker.extract_job(session, newjob)
        session.commit()
        assert material.active_version_id != created["version_id"]
        assert (
            session.get(MaterialVersion, created["version_id"]).extracted_text
            == "큐는 선입선출 자료구조입니다."
        )


async def test_invalid_file_and_cross_course_read(app_db, files_root):
    app, _ = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        bad = await c.post(
            f"/api/v1/courses/{course['id']}/materials",
            data={"kind": "lecture", "week": "1", "visibility": "public"},
            files={"file": ("fake.pdf", b"not pdf", "application/pdf")},
        )
        assert bad.status_code == 422
        result = (await upload(c, course["id"])).json()
        await login(c, "teacher2")
        assert (
            await c.get("/api/v1/materials/" + result["material_id"] + "/file")
        ).status_code == 404


async def test_chat_idempotency_and_job_ownership(app_db, files_root):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        _, section = await setup_course(c)
        code = (await c.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()[
            "join_code"
        ]
        await login(c, "student1")
        await c.post("/api/v1/enrollments", json={"join_code": code})
        path = f"/api/v1/sections/{section['id']}/chat/messages"
        headers = {"Idempotency-Key": "same-question"}
        first = await c.post(path, json={"message": "큐란?"}, headers=headers)
        second = await c.post(path, json={"message": "큐란?"}, headers=headers)
        assert first.status_code == second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]
        assert (
            await c.post(path, json={"message": "다른 질문"}, headers=headers)
        ).status_code == 409
        job = session.get(Job, first.json()["job_id"])
        result = worker.answer_job(session, job)
        assert result["answer_kind"] == "insufficient"
        await login(c, "student2")
        await c.post("/api/v1/enrollments", json={"join_code": code})
        assert (await c.get("/api/v1/jobs/" + job.id)).status_code == 404
