"""Real isolated database/heartbeat queries; never contact providers or modify production."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from lerny import health, storage
from lerny.admin_models import OperationsState, OperationsWorker
from lerny.config import settings
from lerny.main import SCHEMA_REVISION, create_app
from lerny.models import Base, CodeWorker, now
from lerny.tracing import queue


@pytest.fixture
def service(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Readiness must not call a provider")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(storage, "ready", lambda: True)
    config = settings()
    for name, value in dict(deployment="cloud", file_storage="local", trace_backend="queue",
                            admin_instance_id="test-instance", ai_provider="gemini", gemini_calls_enabled=False).items():
        monkeypatch.setattr(config, name, value)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": SCHEMA_REVISION})
    monkeypatch.setattr(health, "engine", lambda: engine)
    monkeypatch.setattr(queue, "engine", lambda: engine)
    with Session(engine) as session:
        session.add_all([OperationsState(id=1), CodeWorker(id="sandbox", ready=True, last_seen_at=now()),
                         OperationsWorker(id="material", kind="material", server_id="test-instance", ready=True)])
        session.commit()
        with TestClient(create_app()) as client:
            yield client, session, config, engine
    engine.dispose()


def check(client, status, reason, learning, execution):
    response = client.get("/api/v1/health/learning")
    assert response.status_code == status
    state = response.json()
    assert (state["reason"], state["learning"], state["code_execution"]) == (reason, learning, execution)
    assert state["ai_required"] is False and state["ai_live_verified"] is False
    caps_response = client.get("/api/v1/capabilities")
    assert caps_response.status_code == 200
    caps = caps_response.json()
    assert (caps["reason"], caps["learning"], caps["code_execution"], caps["code_visualization"]) == (reason, learning, execution, execution)
    return state


def test_online_is_ready_without_ai_calls_or_database_writes(service):
    client, _, _, engine = service
    def readonly(connection, cursor, statement, *args):
        assert statement.lstrip().upper().startswith("SELECT"), statement
    event.listen(engine, "before_cursor_execute", readonly)
    try:
        state = check(client, 200, None, True, True)
        assert state["status"] == "ready"
        assert state["dependencies"]["local_model"] == "gemini_paused"
        assert client.get("/api/v1/health/ready").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", readonly)


@pytest.mark.parametrize("ready,age", [(False, 0), (True, 120)])
def test_offline_or_stale_sandbox_is_partial_learning(service, ready, age):
    client, session, _, _ = service
    sandbox = session.get(CodeWorker, "sandbox")
    sandbox.ready, sandbox.last_seen_at = ready, now() - timedelta(seconds=age)
    session.commit()
    state = check(client, 503, "sandbox_offline", True, False)
    assert state["status"] == "degraded"
    assert client.get("/api/v1/health/ready").status_code == 200


@pytest.mark.parametrize("change", ["stale", "not_ready", "wrong_server"])
def test_grading_worker_must_be_recent_and_from_configured_server(service, change):
    client, session, _, _ = service
    worker = session.get(OperationsWorker, "material")
    if change == "stale": worker.last_seen_at = now() - timedelta(seconds=120)
    elif change == "not_ready": worker.ready = False
    else: worker.server_id = "unrelated"
    session.commit()
    check(client, 503, "grading_worker_offline", True, True)


@pytest.mark.parametrize("flag,reason,execution", [
    ("maintenance", "maintenance", False), ("server_hold", "server_hold", False),
    ("content", "content_disabled", True), ("grading", "grading_disabled", False)])
def test_operations_gates_are_reported(service, flag, reason, execution):
    client, session, _, _ = service
    row = session.get(OperationsState, 1)
    if flag in {"content", "grading"}: row.features = {flag: False}
    else: setattr(row, flag, True)
    session.commit()
    check(client, 503, reason, False, execution)


@pytest.mark.parametrize(("revisions", "accepted"), [
    (["af3e227a01db"], True),
    (["b60d9c84f210"], True),
    (["e83f529cc134"], False),
    (["unknown"], False),
    ([], False),
    (["af3e227a01db", "unknown"], False),
    (["af3e227a01db", "b60d9c84f210"], False),
], ids=["current", "next", "older", "unknown", "empty", "mixed-heads", "both-heads"])
def test_schema_transition_across_health_and_capabilities(service, revisions, accepted):
    client, _, _, engine = service
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
        if revisions:
            connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"),
                               [{"revision": revision} for revision in revisions])
    status = 200 if accepted else 503
    database = "ready" if accepted else "migration_required"
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == status
    assert ready.json()["dependencies"]["database"] == database
    learning = check(client, status, None if accepted else "database_migration_required", accepted, accepted)
    assert learning["dependencies"]["database"] == database


def test_database_failure_is_structured(service, monkeypatch):
    client, _, _, _ = service
    def unavailable(): raise RuntimeError("not configured")
    monkeypatch.setattr(health, "engine", unavailable)
    check(client, 503, "database_unavailable", False, False)


@pytest.mark.parametrize("result", [False, "offline"])
def test_storage_privacy_and_availability_are_required(service, monkeypatch, result):
    client, _, config, _ = service
    monkeypatch.setattr(config, "file_storage", "supabase")
    def probe():
        if result == "offline": raise storage.StorageUnavailable()
        return result
    monkeypatch.setattr(storage, "ready", probe)
    check(client, 503, "storage_unavailable" if result == "offline" else "storage_private_bucket_required", False, False)


def test_uninitialized_operations_row_remains_read_only(service):
    client, session, _, _ = service
    session.delete(session.get(OperationsState, 1))
    session.commit()
    check(client, 200, None, True, True)
    assert session.get(OperationsState, 1) is None
