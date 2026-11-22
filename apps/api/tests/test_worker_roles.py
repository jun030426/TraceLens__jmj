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
        return worker.run_once(worker_kind="embedding")
    def material():
        return worker.run_once(worker_kind="material")
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


@pytest.mark.parametrize("role,cleanups", [("material",1),("embedding",0),("interactive",0)])
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
    assert calls == [{"worker_kind": role}]


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


@pytest.mark.asyncio
async def test_student_claim_partition_and_fifo_with_real_row_lock(cloud_db, monkeypatch):
    from lerny import assessment, practice

    app, db, _ = cloud_db
    assert db.url.host in {"127.0.0.1", "localhost", "::1"} and db.url.database == "lerny_test"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as client:
        await login(client, "teacher1")
        course, _ = await setup_course(client)
    monkeypatch.setattr(settings(), "dedicated_worker", True)
    jobs = [("expired-deck", "extract", "teacher1"), ("vectors", "embed", "student1"),
            ("index", "rag_reindex", "student1"), ("teacher-chat", "chat", "teacher1"),
            ("first", "chat", "student1"), ("second", "practice_grade", "student1"),
            ("third", "grade", "student2")]
    start = now() - timedelta(minutes=10)
    with Session(db) as session:
        owners = dict(session.execute(select(User.login_id, User.id)).all())
        for index, (key, kind, owner) in enumerate(jobs):
            job = Job(id=key, kind=kind, owner_id=owners[owner], course_id=course["id"],
                      created_at=start + timedelta(seconds=index), payload={})
            if key == "expired-deck":
                job.status, job.lease_until = "running", start
            session.add(job)
        session.commit()

    processed = []
    def handle(session, job):
        processed.append(job.id)
        return {}
    monkeypatch.setattr(worker, "answer_job", handle)
    monkeypatch.setattr(practice, "grade", handle)
    monkeypatch.setattr(assessment, "grade_job", handle)
    for key in ("expired-deck", "vectors", "index", "teacher-chat"):
        assert not worker.run_once(key, worker_kind="interactive")
    assert not worker.run_once("first", worker_kind="material")
    assert not worker.run_once("first", worker_kind="embedding")
    with Session(db) as locker:
        locker.scalar(select(Job).where(Job.id == "first").with_for_update())
        assert worker.run_once(worker_kind="interactive")
        assert processed == ["second"]
        locker.rollback()
    assert worker.run_once(worker_kind="interactive") and processed == ["second", "first"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker.run_once(worker_kind="interactive"), range(2))) == [False, True]
    assert worker.run_once("teacher-chat", worker_kind="material")
    assert processed == ["second", "first", "third", "teacher-chat"]
    with Session(db) as session:
        for job in session.scalars(select(Job)):
            if job.id in processed:
                assert (job.status, job.attempt) == ("succeeded", 1)
            else:
                assert job.attempt == 0 and job.status == ("running" if job.id == "expired-deck" else "queued")
