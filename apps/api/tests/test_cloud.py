"""Cloud boundaries against isolated PostgreSQL; Storage/model I/O uses synthetic fakes."""

import json
from datetime import timedelta

import httpx
import pytest
from lerny import cloud_jobs, inference, main, storage, worker
from lerny import db as db_module
from lerny.config import settings
from lerny.models import Base, Chunk, Job, MaterialVersion, ModelCall, Question, User, now
from lerny.security import hasher
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from test_identity_courses import login, setup_course

pytestmark = pytest.mark.asyncio
AUTH = {"Authorization": "Bearer " + "w" * 40}
CRON = {"Authorization": "Bearer " + "c" * 40}
SOURCE = "큐는 선입선출 자료구조입니다. 큐에서는 먼저 들어온 항목이 먼저 나옵니다."


@pytest.fixture
def cloud_db(monkeypatch, tmp_path):
    url = db_module.engine().url.set(database="lerny_test")
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.database == "lerny_test"
    isolated = create_engine(url)
    Base.metadata.drop_all(isolated)
    Base.metadata.create_all(isolated)
    with isolated.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) primary key)")
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": main.SCHEMA_REVISION},
        )
    for module in (db_module, inference, main, worker, cloud_jobs):
        monkeypatch.setattr(module, "engine", lambda: isolated)
    config = settings()
    for name, value in {
        "deployment": "cloud",
        "cookie_secure": True,
        "allowed_origins": ["https://lerny.example"],
        "ai_worker_token": SecretStr("w" * 40),
        "cron_secret": SecretStr("c" * 40),
        "runtime_root": tmp_path / "unused-PC-data",
    }.items():
        monkeypatch.setattr(config, name, value)
    objects = {}
    monkeypatch.setattr(storage, "signed_upload", lambda key: "https://storage.example/" + key)
    monkeypatch.setattr(
        storage, "signed_download", lambda key, filename: "https://storage.example/" + key
    )
    monkeypatch.setattr(storage, "put", lambda key, content: objects.__setitem__(key, content))
    monkeypatch.setattr(storage, "delete_object", lambda key: objects.pop(key, None))
    monkeypatch.setattr(storage, "ready", lambda: True)

    def download(key, limit):
        content = objects[key]
        if len(content) > limit:
            raise ValueError("FILE_TOO_LARGE")
        return content

    monkeypatch.setattr(storage, "download", download)
    with Session(isolated) as session:
        for name, role in [
            ("teacher1", "teacher"),
            ("student1", "student"),
            ("student2", "student"),
        ]:
            session.add(
                User(
                    login_id=name,
                    display_name=name,
                    role=role,
                    password_hash=hasher.hash("Test-only-password-123"),
                )
            )
        session.commit()
    yield main.create_app(), isolated, objects
    assert not config.runtime_root.exists(), "Cloud service wrote to the PC runtime"
    isolated.dispose()


async def direct_upload(client, objects, course_id):
    content = SOURCE.encode()
    prepared = await client.post(
        f"/api/v1/courses/{course_id}/uploads",
        json={"filename": "lecture.txt", "size": len(content), "week": 1},
    )
    assert prepared.status_code == 201, prepared.text
    ticket = prepared.json()
    assert "service" not in ticket and "database_url" not in ticket
    objects[ticket["url"].removeprefix("https://storage.example/")] = content
    completed = await client.post(f"/api/v1/uploads/{ticket['upload_id']}/complete", json={})
    assert completed.status_code == 201, completed.text
    assert (
        await client.post(f"/api/v1/uploads/{ticket['upload_id']}/complete", json={})
    ).json() == completed.json()
    return completed.json()


async def tick(client):
    response = await client.post("/api/internal/jobs/tick", headers=CRON, json={})
    assert response.status_code == 200, response.text


def synthetic_response(task):
    body = task["body"]
    if task["operation"] == "embed":
        return {"embeddings": [[1.0, 0.0] for _ in body["input"]]}
    schema = body["format"]
    properties = schema["properties"]
    if "concepts" in properties:
        value = {"concepts": [{"name": "큐", "quote": "큐는 선입선출 자료구조입니다."}]}
    elif "questions" in properties:
        keys = schema["$defs"]["Source"]["properties"]["chunk_id"]["enum"]
        common = {
            "answer_index": 0,
            "explanation": "먼저 들어온 항목이 먼저 나옵니다.",
            "sources": [{"chunk_id": keys[0]}],
        }
        value = {
            "questions": [
                {
                    **common,
                    "kind": "mcq",
                    "prompt": "큐에서 먼저 나오는 항목은?",
                    "options": ["먼저 들어온 항목", "마지막 항목", "임의 항목", "없음"],
                    "criteria": [],
                },
                {
                    **common,
                    "kind": "mcq",
                    "prompt": "큐의 항목 처리 순서는?",
                    "options": ["선입선출", "후입선출", "무작위", "역순"],
                    "criteria": [],
                },
                {
                    **common,
                    "kind": "essay",
                    "prompt": "큐의 처리 순서를 설명하세요.",
                    "options": [],
                    "criteria": keys[:2],
                },
            ]
        }
    elif "correct_option" in properties:
        value = {"correct_option": properties["correct_option"]["enum"][0]}
    elif "supported" in properties:
        value = {"supported": True, "unambiguous": True, "answer_correct": True}
    elif "criteria" in properties:
        value = {
            "certain": True,
            "criteria": {
                key: {"score": 100, "answer_source_ids": ["A1"]}
                for key in properties["criteria"]["properties"]
            },
        }
    else:
        raise AssertionError("Unexpected synthetic model request")
    return {"message": {"content": json.dumps(value, ensure_ascii=False)}}


async def drain(client, isolated, target_kind):
    for _ in range(35):
        await tick(client)
        claimed = await client.post(
            "/api/internal/ai/claim", headers=AUTH, json={"worker_id": "fake-model"}
        )
        assert claimed.status_code == 200, claimed.text
        task = claimed.json()["task"]
        if task:
            completed = await client.post(
                f"/api/internal/ai/tasks/{task['id']}/result",
                headers=AUTH,
                json={
                    "worker_id": "fake-model",
                    "lease_token": task["lease_token"],
                    "response": synthetic_response(task),
                },
            )
            assert completed.status_code == 200, completed.text
        with Session(isolated) as session:
            jobs = list(session.scalars(select(Job).where(Job.kind == target_kind)))
            assert not any(job.status == "failed" for job in jobs), [
                (j.kind, j.error_code) for j in jobs
            ]
            if jobs and all(job.status == "succeeded" for job in jobs):
                return
    raise AssertionError("Cloud pipeline did not finish")


async def test_general_service_and_file_processing_without_PC(cloud_db):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lerny.example"
    ) as client:
        await login(client, "teacher1")
        course, _ = await setup_course(client)
        uploaded = await direct_upload(client, objects, course["id"])
        await tick(client)
        with Session(isolated) as session:
            version = session.get(MaterialVersion, uploaded["version_id"])
            assert version.extracted_text == SOURCE and version.status == "extracted"
            assert session.scalar(select(func.count()).select_from(Chunk)) == 1
            job = session.scalar(select(Job).where(Job.kind == "embed"))
            assert job.status == "waiting_ai"
        assert (await client.get("/api/v1/health/ready")).status_code == 200
        assert (await client.get("/api/v1/ai/status")).json()["status"] == "offline"
        assert (
            await client.get(f"/api/v1/materials/{uploaded['material_id']}/file")
        ).status_code == 303
        await login(client, "student2")
        assert (
            await client.get(f"/api/v1/materials/{uploaded['material_id']}/file")
        ).status_code == 404
        # Ordinary data remains usable with no model worker/localhost calls.
        await login(client, "teacher1")
        assert (await client.get(f"/api/v1/courses/{course['id']}/materials")).status_code == 200


async def test_inference_replay_generation_and_grading(cloud_db):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lerny.example"
    ) as client:
        await login(client, "teacher1")
        course, section = await setup_course(client)
        await direct_upload(client, objects, course["id"])
        await drain(client, isolated, "questions")
        with Session(isolated) as session:
            assert session.scalar(select(func.count()).select_from(Question)) == 3, (
                "Replays duplicated application writes"
            )
        code = (await client.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()[
            "join_code"
        ]
        await login(client, "student1")
        assert (
            await client.post("/api/v1/enrollments", json={"join_code": code})
        ).status_code == 201
        daily = (await client.post(f"/api/v1/sections/{section['id']}/daily", json={})).json()
        assert len(daily["items"]) == 3
        for item in daily["items"]:
            submitted = await client.post(
                f"/api/v1/learning-sessions/{daily['id']}/questions/{item['id']}/submit",
                json={"answer": "0" if item["kind"] == "mcq" else SOURCE},
                headers={"Idempotency-Key": item["id"]},
            )
            assert submitted.status_code == 202, submitted.text
        await drain(client, isolated, "grade")
        final = (await client.get(f"/api/v1/learning-sessions/{daily['id']}")).json()
        assert all(item["attempt"]["status"] == "graded" for item in final["items"])


async def test_worker_auth_cancel_expiry_and_retry(cloud_db):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lerny.example"
    ) as client:
        assert (
            await client.post("/api/internal/ai/claim", json={"worker_id": "test"})
        ).status_code == 401
        assert (await client.post("/api/internal/jobs/tick", headers=AUTH)).status_code == 401
        await login(client, "teacher1")
        course, _ = await setup_course(client)
        await direct_upload(client, objects, course["id"])
        await tick(client)
        task = (
            await client.post("/api/internal/ai/claim", headers=AUTH, json={"worker_id": "test"})
        ).json()["task"]
        with Session(isolated) as session:
            job_id = session.get(ModelCall, task["id"]).job_id
            session.get(ModelCall, task["id"]).lease_until = now() - timedelta(seconds=1)
            session.commit()
        body = {
            "worker_id": "test",
            "lease_token": task["lease_token"],
            "response": synthetic_response(task),
        }
        assert (
            await client.post(
                f"/api/internal/ai/tasks/{task['id']}/result", headers=AUTH, json=body
            )
        ).status_code == 409
        assert (await client.post(f"/api/v1/jobs/{job_id}/cancel", json={})).status_code == 200
        assert (
            await client.post(
                f"/api/internal/ai/tasks/{task['id']}/result", headers=AUTH, json=body
            )
        ).status_code == 409
        assert (
            await client.post("/api/internal/ai/claim", headers=AUTH, json={"worker_id": "test"})
        ).json()["task"] is None


async def test_failed_model_request_can_be_retried_with_new_generation(cloud_db):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        await login(client, "teacher1")
        course, _ = await setup_course(client)
        uploaded = await direct_upload(client, objects, course["id"])
        await tick(client)
        old = (await client.post("/api/internal/ai/claim", headers=AUTH, json={"worker_id": "test"})).json()["task"]
        failed = await client.post(f"/api/internal/ai/tasks/{old['id']}/result", headers=AUTH,
            json={"worker_id": "test", "lease_token": old["lease_token"], "error": True})
        assert failed.status_code == 200
        with Session(isolated) as session:
            job_id = session.get(ModelCall, old["id"]).job_id
            assert session.get(Job, job_id).status == "failed"
        assert (await client.post(f"/api/v1/jobs/{job_id}/retry", json={})).status_code == 202
        await tick(client)
        new = (await client.post("/api/internal/ai/claim", headers=AUTH, json={"worker_id": "test"})).json()["task"]
        assert new["id"] != old["id"]
        stale = {"worker_id": "test", "lease_token": old["lease_token"], "response": synthetic_response(old)}
        assert (await client.post(f"/api/internal/ai/tasks/{old['id']}/result", headers=AUTH, json=stale)).status_code == 409
        body = {"worker_id": "test", "lease_token": new["lease_token"], "response": synthetic_response(new)}
        assert (await client.post(f"/api/internal/ai/tasks/{new['id']}/result", headers=AUTH, json=body)).status_code == 200
        assert (await client.post(f"/api/internal/ai/tasks/{new['id']}/result", headers=AUTH, json=body)).status_code == 200
        with Session(isolated) as session:
            assert session.get(MaterialVersion, uploaded["version_id"]).status == "ready"


async def test_cloud_upload_checks_owner_size_format_and_origin(cloud_db):
    app, _, objects = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        denied = await client.post("/api/v1/auth/login", headers={"Origin": "https://other.example"}, json={
            "login_id": "teacher1", "password": "Test-only-password-123"})
        assert denied.status_code == 403
        await login(client, "teacher1")
        course, _ = await setup_course(client)
        ticket = (await client.post(f"/api/v1/courses/{course['id']}/uploads", json={
            "filename": "bad.pdf", "size": 3})).json()
        objects[ticket["url"].removeprefix("https://storage.example/")] = b"bad"
        assert (await client.post(f"/api/v1/uploads/{ticket['upload_id']}/complete", json={})).status_code == 422
        await login(client, "student1")
        assert (await client.post(f"/api/v1/uploads/{ticket['upload_id']}/complete", json={})).status_code == 404
        await login(client, "teacher1")
        objects[ticket["url"].removeprefix("https://storage.example/")] = b"size mismatch"
        assert (await client.post(f"/api/v1/uploads/{ticket['upload_id']}/complete", json={})).status_code == 422
        oversized = await client.post(f"/api/v1/courses/{course['id']}/uploads", json={
            "filename": "huge.pdf", "size": 51 * 1024 * 1024})
        assert oversized.status_code == 413
