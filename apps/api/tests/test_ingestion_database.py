"""Real PostgreSQL constraints, leases, publication and authenticated API tests."""

import json
import os
import re
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from lerny.ingestion_store import MODEL, PIPELINE, SupabaseIngestion
from lerny.ingestion_worker import process
from lerny.models import Base, Course, Term, UploadIntent, User
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from test_ingestion_worker import Engine, MemoryStore


@pytest.fixture(scope="module")
def database():
    raw = os.environ.get("LERNY_INGESTION_TEST_URL")
    if not raw:
        pytest.skip("Use scripts/test_ingestion.py for an isolated local database")
    url = make_url(raw)
    assert url.host == "127.0.0.1" and url.database.startswith("lerny_ingestion_test_")
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    roles = json.loads(os.environ["LERNY_INGESTION_TEST_ROLES"])
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("create extension if not exists vector")
        c.execute("create extension if not exists pgcrypto")
    engine = create_engine(raw)
    Base.metadata.create_all(engine)
    root = Path(__file__).resolve().parents[3]
    with psycopg.connect(dsn, autocommit=True) as c:
        for name in ("ingestion-base.sql", "ingestion-worker.sql"):
            source = (root / "deploy" / name).read_text(encoding="utf-8")
            for label, role in roles.items():
                source = re.sub(r"\b" + label + r"\b", role, source)
            c.execute(source)
    with Session(engine) as s:
        user = User(login_id="ingestion_teacher", display_name="Teacher", role="teacher", password_hash="unused")
        other = User(login_id="ingestion_other", display_name="Other", role="teacher", password_hash="unused")
        term = Term(name="Test", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31))
        s.add_all([user, other, term])
        s.flush()
        course = Course(title="Ingestion test", lead_teacher_id=user.id, term_id=term.id, teaching_language="python")
        s.add(course)
        s.commit()
        ids = {"teacher": user.id, "other": other.id, "course": course.id}
    yield {"dsn": dsn, "roles": roles, "engine": engine, **ids}
    engine.dispose()


class SqlStore(MemoryStore):
    def __init__(self, database):
        super().__init__()
        self.database = database

    def connect(self):
        c = psycopg.connect(self.database["dsn"], autocommit=True)
        c.execute(sql.SQL("set role {}").format(sql.Identifier(self.database["roles"]["service_role"])))
        return c

    def rpc(self, name, **params):
        values = [Jsonb(v) if isinstance(v, (dict, list)) else UUID(v) if k in {"p_job_id", "p_lease_token", "p_source_id"} else v
                  for k, v in params.items()]
        statement = sql.SQL("SELECT to_jsonb(public.{}({}))").format(sql.Identifier(name),
            sql.SQL(",").join(sql.SQL("{} => %s").format(sql.Identifier(k)) for k in params))
        with self.connect() as c:
            rows = c.execute(statement, values).fetchall()
        return [r[0] for r in rows] if name == "ingestion_claim" else rows[0][0]

    claim = SupabaseIngestion.claim
    heartbeat = SupabaseIngestion.heartbeat
    source = SupabaseIngestion.source
    checkpoints = SupabaseIngestion.checkpoints
    checkpoint = SupabaseIngestion.checkpoint
    publish = SupabaseIngestion.publish
    fail = SupabaseIngestion.fail

    def rows(self, table, **filters):
        with self.connect() as c:
            query = sql.SQL("select to_jsonb(t) from public.{} t where {}").format(sql.Identifier(table),
                sql.SQL(" AND ").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in filters))
            return [r[0] for r in c.execute(query, [UUID(v) for v in filters.values()]).fetchall()]

    def upsert(self, job, table, row):
        from lerny.ingestion_store import TABLES
        row = {**row, "job_id": UUID(job["id"]), "lease_token": UUID(job["lease_token"])}
        values = [Jsonb(v) if isinstance(v, (dict, list)) and k != "embedding" else str(v) if k == "embedding" else v
                  for k, v in row.items()]
        query = sql.SQL("insert into public.{} ({}) values ({}) on conflict(job_id,{}) do update set {}").format(
            sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL(",").join(sql.Placeholder() for _ in row), sql.Identifier(TABLES[table]),
            sql.SQL(",").join(sql.SQL("{}=excluded.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in row))
        with self.connect() as c:
            c.execute(query, values)

    def counts(self, job):
        with self.connect() as c:
            return {t: c.execute(sql.SQL("select count(*) from public.{} where job_id=%s").format(sql.Identifier(t)),
                                 (UUID(job["id"]),)).fetchone()[0]
                    for t in ("course_vectors", "concept_quizzes", "shorts_scripts", "lab_quizzes")}


@pytest.fixture
def store(database):
    store = SqlStore(database)
    with psycopg.connect(database["dsn"], autocommit=True) as c:
        # Only this dedicated test DB is ever reset.
        c.execute("truncate ingestion_sources,ingestion_jobs,ingestion_checkpoints,course_vectors,concept_quizzes,lab_quizzes,shorts_scripts cascade")
        source = c.execute("""insert into ingestion_sources(course_id,source_key,title,week_number,visibility,created_by)
            values(%s,'test','스택',1,'public',%s) returning id""", (database["course"], database["teacher"])).fetchone()[0]
    import hashlib
    queued = store.rpc("ingestion_enqueue", p_source_id=str(source), p_file_name="source.txt",
                       p_file_path="ingestion/raw/test.txt", p_file_hash=hashlib.sha256(b"lecture").hexdigest(),
                       p_pipeline_version=PIPELINE, p_config={"embedding_model": MODEL})
    store.queued = queued
    return store


class FullEngine(Engine):
    def generate(self, _):
        return {"concept_quizzes": [{"quiz_key": "q", "concept_label": "stack", "question_type": "principle",
                 "difficulty": "low", "question": "스택은?", "options": ["A", "B", "C", "D"],
                 "answer": {"answer_index": 0}, "explanation": "근거", "hints": ["1", "2", "3"],
                 "evidence": [{"quote": "스택은 후입선출"}], "generator_version": PIPELINE}],
                "shorts_scripts": [{"shorts_key": "s", "course_id": self.course, "concept_id": "stack",
                 "title": "스택", "template_variables": {"lecture_script": "스택은 후입선출입니다."},
                 "evidence": [{"quote": "스택은 후입선출"}], "generator_version": PIPELINE}]}

    def __init__(self, job, source, lease):
        super().__init__(job, source, lease)
        self.course = source["course_id"]


def test_actual_rpc_stage_pipeline_and_publish(store, tmp_path):
    job = store.claim("worker-a")
    assert store.claim("worker-b") is None
    result = process(store, job, FullEngine, tmp_path)
    assert result["status"] == "COMPLETED"
    assert result["result"]["shorts_scripts"] == 1
    assert result["result"]["vectors"] == 1
    assert store.rows("ingestion_sources", id=job["source_id"])[0]["active_job_id"] == job["id"]
    assert not list(tmp_path.iterdir())


def test_worker_claim_does_not_consume_other_pipeline(store):
    with psycopg.connect(store.database["dsn"], autocommit=True) as c:
        c.execute("update ingestion_jobs set pipeline_version='other-engine'")
    assert store.claim("worker") is None
    assert store.rows("ingestion_jobs", id=store.queued["id"])[0]["status"] == "PENDING"


def test_stale_lease_and_stage_guards(store):
    job = store.claim("a")
    with pytest.raises(psycopg.Error, match="RESULT_STAGE_NOT_OPEN"):
        store.upsert(job, "course_vectors", {"chunk_key": "c", "content": "x", "embedding_model": MODEL,
                                             "embedding": [1.0] + [0.0] * 767})
    with psycopg.connect(store.database["dsn"], autocommit=True) as c:
        c.execute("update ingestion_jobs set lease_until=now()-interval '1 second' where id=%s", (UUID(job["id"]),))
    assert not store.heartbeat(job)
    reclaimed = store.claim("b")
    assert reclaimed["lease_token"] != job["lease_token"]
    with pytest.raises(psycopg.Error, match="STALE_LEASE"):
        store.checkpoint(job, 1, {"file_hash": job["file_hash"]}, [])


def test_wrong_count_or_missing_shorts_cannot_publish(store, tmp_path):
    job = store.claim("a")
    class StopBeforePublish(SqlStore):
        pass
    original = store.publish
    store.publish = lambda *_: None
    process(store, job, FullEngine, tmp_path)
    store.publish = original
    with pytest.raises(psycopg.Error, match="RESULT_COUNTS_MISMATCH"):
        store.publish(job, {"course_vectors": 2, "concept_quizzes": 1, "lab_quizzes": 0})
    with psycopg.connect(store.database["dsn"], autocommit=True) as c:
        c.execute("delete from shorts_scripts where job_id=%s", (UUID(job["id"]),))
    with pytest.raises(psycopg.Error, match="SHORTS_RESULTS_REQUIRED"):
        store.publish(job, {"course_vectors": 1, "concept_quizzes": 1, "lab_quizzes": 0})


def test_database_acl_and_shared_pacing(store):
    database = store.database
    with psycopg.connect(database["dsn"], autocommit=True) as c:
        for label in ("anon", "authenticated"):
            role = database["roles"][label]
            assert not c.execute("select has_table_privilege(%s,'public.shorts_scripts','SELECT')", (role,)).fetchone()[0]
            assert not c.execute("select has_function_privilege(%s,'public.ingestion_claim(text,integer)','EXECUTE')", (role,)).fetchone()[0]
    first = store.rpc("ingestion_reserve_api_slot")
    second = store.rpc("ingestion_reserve_api_slot")
    assert second - first >= 4.0


def test_api_rejects_another_course_teacher_and_hides_lease(store):
    from lerny.db import db
    from lerny.main import create_app
    from lerny.security import current_user
    app = create_app()
    database = store.database
    with Session(database["engine"]) as session:
        app.dependency_overrides[db] = lambda: session
        app.dependency_overrides[current_user] = lambda: session.get(User, database["other"])
        client = TestClient(app)
        response = client.get("/api/v1/ingestion/jobs/" + store.queued["id"])
        assert response.status_code == 404
        app.dependency_overrides[current_user] = lambda: session.get(User, database["teacher"])
        response = client.get("/api/v1/ingestion/jobs/" + store.queued["id"])
        assert response.status_code == 200
        assert "lease_token" not in response.json()


def test_authenticated_upload_enqueues_once_and_checks_bucket_limit(store, monkeypatch):
    from types import SimpleNamespace

    from lerny import ingestion_api, storage
    from lerny.db import db
    from lerny.main import create_app
    from lerny.security import current_user
    objects = {}
    class Files:
        def copy_original(self, source, target):
            objects.setdefault(target, objects[source])
        def download(self, key, target, limit):
            import hashlib
            content = objects[key]
            assert len(content) <= limit
            target.write_bytes(content)
            return hashlib.sha256(content).hexdigest()
        def close(self):
            pass
    monkeypatch.setattr(ingestion_api, "settings", lambda: SimpleNamespace(
        uses_supabase_storage=True, storage_bucket="lerny-materials", gemini_answer_model="synthetic-test-only"))
    monkeypatch.setattr(ingestion_api, "SupabaseIngestion", Files)
    monkeypatch.setattr(storage, "signed_upload", lambda key: "https://test.invalid/" + key)
    monkeypatch.setattr(storage, "delete_object", lambda key: objects.pop(key, None))
    monkeypatch.setattr(storage, "request", lambda *a, **k: SimpleNamespace(json=lambda: {"public": False, "file_size_limit": 50 * 1024 * 1024}))
    database = store.database
    app = create_app()
    with Session(database["engine"]) as session:
        app.dependency_overrides[db] = lambda: session
        app.dependency_overrides[current_user] = lambda: session.get(User, database["teacher"])
        client = TestClient(app)
        body = {"filename": "lecture.txt", "size": 7, "title": "스택", "source_key": "uploaded",
                "allow_ai_processing": True}
        path = f"/api/v1/courses/{database['course']}/ingestion/uploads"
        assert client.post(path, json={**body, "size": 51 * 1024 * 1024}).status_code == 413
        prepared = client.post(path, json=body)
        assert prepared.status_code == 201
        upload_id = prepared.json()["upload_id"]
        intent = session.get(UploadIntent, upload_id)
        objects[intent.object_key] = b"lecture"
        endpoint = f"/api/v1/ingestion/uploads/{upload_id}/complete"
        first, second = client.post(endpoint), client.post(endpoint)
        assert first.status_code == 201 and first.json() == second.json()
        row = store.rows("ingestion_jobs", id=first.json()["job_id"])[0]
        assert row["file_path"].startswith("ingestion/raw/")
        assert row["pipeline_version"] == PIPELINE
