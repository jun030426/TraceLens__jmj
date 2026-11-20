import asyncio
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.models import CodeRun, CodeWorker, User, now
from lerny.tracing import cloud_worker, queue
from lerny.tracing.envelope import TraceBuilder
from test_cloud import cloud_db  # noqa: F401 -- shared isolated PostgreSQL fixture
from test_identity_courses import login, setup_course

pytestmark = pytest.mark.asyncio


@pytest.fixture
def queued(cloud_db, monkeypatch):
    app, isolated, objects = cloud_db
    monkeypatch.setattr(settings(), "trace_backend", "queue")
    monkeypatch.setattr(queue, "engine", lambda: isolated)
    monkeypatch.setattr(cloud_worker, "engine", lambda: isolated)
    cloud_worker.touch("synthetic-worker")
    yield app, isolated


async def test_api_to_independent_worker_and_cleanup(queued, monkeypatch):
    app, isolated = queued
    executed = []
    def synthetic(language, source):
        executed.append((language, source))
        return TraceBuilder(language).envelope(source)
    monkeypatch.setattr(cloud_worker, "run_in_sandbox", synthetic)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        await login(client, "teacher1")
        _, section = await setup_course(client)
        pending = asyncio.create_task(client.post(f"/api/v1/sections/{section['id']}/practice/trace", json={"source": "x = 1"}))
        for _ in range(40):
            if await asyncio.to_thread(cloud_worker.run_once):
                break
            await asyncio.sleep(0.05)
        response = await asyncio.wait_for(pending, 5)
        assert response.status_code == 200
        assert response.json()["language"] == "python"
        assert executed == [("python", "x = 1")]
        with Session(isolated) as session:
            assert session.scalar(select(func.count()).select_from(CodeRun)) == 0


async def test_queue_access_limits_size_and_offline_worker(queued):
    app, isolated = queued
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        await login(client, "teacher1")
        _, section = await setup_course(client)
        endpoint = f"/api/v1/sections/{section['id']}/practice/trace"
        assert (await client.post(endpoint, json={"source": "가" * 12000})).status_code == 413
        with Session(isolated) as session:
            teacher = session.scalar(select(User).where(User.login_id == "teacher1"))
            session.add(CodeRun(owner_id=teacher.id, section_id=section["id"], language="python",
                                source="x=1", expires_at=now() + timedelta(minutes=1)))
            session.commit()
        assert (await client.post(endpoint, json={"source": "x=1"})).status_code == 429
        await login(client, "student2")
        assert (await client.post(endpoint, json={"source": "x=1"})).status_code == 404
        await login(client, "teacher1")
        with Session(isolated) as session:
            worker = session.get(CodeWorker, "synthetic-worker")
            worker.last_seen_at = now() - timedelta(minutes=5)
            session.commit()
        assert (await client.post(endpoint, json={"source": "x=1"})).status_code == 503


async def test_worker_failure_erases_source_and_expired_requests(queued, monkeypatch):
    _, isolated = queued
    def failed(language, source):
        raise RuntimeError("private debugger error must not be logged")
    monkeypatch.setattr(cloud_worker, "run_in_sandbox", failed)
    app = queued[0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        await login(client, "teacher1")
        _, section = await setup_course(client)
        with Session(isolated) as session:
            owner = session.scalar(select(User.id).where(User.login_id == "teacher1"))
            item = CodeRun(owner_id=owner, section_id=section["id"], language="c", source="private code",
                           expires_at=now() + timedelta(minutes=1))
            session.add(item); session.commit(); run_id = item.id
        assert cloud_worker.run_once()
        with Session(isolated) as session:
            item = session.get(CodeRun, run_id)
            assert item.source == "" and item.error_code == "SANDBOX_FAILED" and item.result is None
            item.expires_at = now() - timedelta(seconds=1)
            session.commit()
        cloud_worker.touch("synthetic-worker")
        with Session(isolated) as session:
            assert session.get(CodeRun, run_id) is None
