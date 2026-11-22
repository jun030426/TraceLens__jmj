import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lerny import material_daemon, rag_api, worker
from lerny.config import settings
from lerny.models import Job, User, now
from test_cloud import cloud_db
from test_identity_courses import login, setup_course


@pytest.mark.asyncio
async def test_postgres_skip_locked_and_both_workers_claim_once(cloud_db, monkeypatch):
    app, db, _ = cloud_db
    assert db.url.host in {"127.0.0.1", "localhost", "::1"} and db.url.database == "lerny_test"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
    monkeypatch.setattr(settings(), "dedicated_worker", True)
    with Session(db) as session:
        owner = session.scalar(select(User.id).where(User.login_id == "teacher1"))
        for index, (name, kind) in enumerate([("old","rag_reindex"),("new","rag_reindex"),("document","extract")]):
            session.add(Job(id=name, owner_id=owner, course_id=course["id"], kind=kind,
                            created_at=now()+timedelta(seconds=index), payload={}))
        session.commit()
    counts = Counter()
    overlap = threading.Barrier(2)
    def handler(session, job):
        counts[job.id] += 1
        if job.id != "old":
            overlap.wait(timeout=8)
        return {"handled":job.id}
    monkeypatch.setattr(rag_api, "reindex_job", handler)
    monkeypatch.setattr(worker, "extract_job", handler)
    def embedding():
        return worker.run_once(kinds=worker.EMBEDDING_JOBS, worker_kind="embedding")
    def material():
        return worker.run_once(exclude_kinds=worker.EMBEDDING_JOBS)
    with Session(db) as locker:
        locker.scalar(select(Job).where(Job.id=="old").with_for_update())
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(embedding), pool.submit(material)
            assert first.result(timeout=12) and second.result(timeout=12)
        assert counts == {"document":1,"new":1}
        assert not embedding() and not material()
        locker.rollback()
    # Even when two consumers compete for the remaining row exactly one executes it.
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: embedding(), range(2))) == [False, True]
    assert counts == {"document":1, "new":1, "old":1}
    with Session(db) as session:
        assert all(j.status == "succeeded" and j.attempt == 1 for j in session.scalars(select(Job)))


@pytest.mark.parametrize("role,cleanups", [("material",1),("embedding",0)])
def test_only_material_daemon_cleans(monkeypatch, role, cleanups):
    monkeypatch.setattr(settings(), "dedicated_worker", True)
    cleaned, calls = [], []
    monkeypatch.setattr(material_daemon, "cleanup", lambda: cleaned.append(1))
    def stop(**kwargs):
        calls.append(kwargs)
        raise SystemExit
    monkeypatch.setattr(material_daemon, "run_once", stop)
    with pytest.raises(SystemExit):
        material_daemon.main(role)
    assert len(cleaned) == cleanups
    assert calls[0]["kinds"] == (worker.EMBEDDING_JOBS if role == "embedding" else None)
    assert calls[0]["exclude_kinds"] == (worker.EMBEDDING_JOBS if role == "material" else ())


@pytest.mark.parametrize("provider,expected", [("gemini",0),("ollama",1)])
def test_cloud_tick_respects_cleanup_owner(monkeypatch, provider, expected):
    from lerny import admin_control, cloud_jobs
    calls = []
    monkeypatch.setattr(settings(), "deployment", "cloud")
    monkeypatch.setattr(settings(), "ai_provider", provider)
    monkeypatch.setattr(admin_control, "tick", lambda:None)
    monkeypatch.setattr(worker, "run_once", lambda:False)
    monkeypatch.setattr(cloud_jobs, "cleanup", lambda:calls.append(1))
    assert cloud_jobs.tick() == {"processed":0}
    assert len(calls) == expected
