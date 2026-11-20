"""Paused Gemini runtime and explicit migration; synthetic data and fake responses only."""

import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from lerny import health, retrieval, worker
from lerny.gemini_runtime import migrate_extracted_materials
from lerny.local_network import guard_loopback
from lerny.models import Job, Material, MaterialVersion
from test_gemini_integration import configured, fake_provider, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401


@pytest.fixture
def paused(integration, configured, monkeypatch):  # noqa: F811
    configured.gemini_calls_enabled = False
    client, session, _ = integration
    monkeypatch.setattr(worker, "heartbeat", lambda *args: None)
    monkeypatch.setattr(health, "engine", lambda: session.bind)
    return client, session, configured


def test_status_names_gemini_and_paused_without_model_probe(paused):
    client, _, config = paused
    response = client.get("/api/v1/ai/status")
    assert response.status_code == 200
    state = response.json()
    assert state["provider"] == "gemini" and state["status"] == "gemini_paused"
    assert state["key_configured"] and not state["calls_enabled"] and not state["live_verified"]
    assert "일시 중지" in state["message"]
    health = client.get("/api/v1/health/learning")
    assert health.json()["dependencies"]["local_model"] == "gemini_paused"
    config.gemini_calls_enabled = True
    assert client.get("/api/v1/ai/status").json()["status"] == "gemini"


def test_embedding_only_key_resumes_index_without_spinning_on_content_job(paused, monkeypatch):
    from pydantic import SecretStr
    from lerny import rag_api
    _, session, config = paused
    config.gemini_calls_enabled = True
    config.gemini_api_key = SecretStr('')
    config.gemini_embedding_api_key = SecretStr('synthetic-embedding-only')
    monkeypatch.setattr(rag_api, 'reindex_job', lambda *_: {'synthetic': True})
    chat = Job(owner_id='teacher', course_id='course', kind='chat', status='waiting_ai',
               error_code='GEMINI_KEY_REQUIRED', payload={})
    session.add(chat)
    session.flush()
    index = Job(owner_id='teacher', course_id='course', kind='rag_reindex', status='waiting_ai',
                error_code='GEMINI_KEY_REQUIRED', payload={})
    session.add(index)
    session.commit()
    assert worker.run_once()
    session.expire_all()
    assert index.status == 'succeeded' and chat.status == 'waiting_ai'
    assert not worker.run_once()


@pytest.mark.parametrize(
    "kind", ["chat", "auto_concepts", "questions", "grade", "rag_reindex", "narration_lesson"]
)
def test_remote_jobs_wait_without_attempting_provider(paused, fake_provider, kind):  # noqa: F811
    _, session, _ = paused
    job = Job(owner_id="teacher", course_id="course", kind=kind, payload={})
    session.add(job)
    session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "waiting_ai" and job.error_code == "GEMINI_CALLS_DISABLED"
    assert job.attempt == 0 and fake_provider == []
    assert worker.run_once(job.id) is False


def test_extract_continues_and_embedding_resumes_with_mock_only(paused, fake_provider, monkeypatch):  # noqa: F811
    _, session, config = paused
    version = session.get(MaterialVersion, "version")
    material = session.get(Material, "material")
    material.active_version_id = None
    version.status = "queued"
    monkeypatch.setattr(
        worker, "extract", lambda *_: [("Synthetic stack explanation", {"page": 1})]
    )
    job = Job(
        owner_id="teacher", course_id="course", kind="extract", payload={"version_id": "version"}
    )
    session.add(job)
    session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded" and version.extracted_text == "Synthetic stack explanation"
    embed = session.scalar(select(Job).where(Job.kind == "embed"))
    assert embed.payload["_ai_provider"] == "gemini"
    assert worker.run_once(embed.id)
    session.expire_all()
    assert embed.status == "waiting_ai" and version.status == "extracted"
    assert version.error_code == "GEMINI_CALLS_DISABLED" and fake_provider == []
    assert worker.run_once(embed.id) is False
    config.gemini_calls_enabled = True  # provider.request is mocked; no external HTTP is allowed.
    assert worker.run_once(embed.id)
    session.expire_all()
    assert embed.status == "succeeded" and embed.attempt == 1
    assert version.status == "ready" and version.error_code is None
    assert fake_provider[0][0] == "models/gemini-embedding-2:embedContent"


@pytest.mark.parametrize(
    "visibility,internal_use", [("private", "none"), ("public", "validation_grading")]
)
def test_excluded_materials_remain_local_without_followup_generation(
    paused, fake_provider, monkeypatch, visibility, internal_use  # noqa: F811
):  # noqa: F811
    _, session, _ = paused
    material = session.get(Material, "material")
    material.visibility, material.internal_use, material.kind = visibility, internal_use, "lecture"
    monkeypatch.setattr(worker, "extract", lambda *_: [("PRIVATE INTERNAL EXAMPLE", {"page": 1})])
    job = Job(
        owner_id="teacher", course_id="course", kind="extract", payload={"version_id": "version"}
    )
    session.add(job)
    session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert session.get(MaterialVersion, "version").status == "ready"
    assert list(session.scalars(select(Job).where(Job.kind != "extract"))) == []
    assert fake_provider == []


def test_explicit_migration_is_idempotent_preserves_history_and_text(paused, fake_provider):  # noqa: F811
    _, session, _ = paused
    version = session.get(MaterialVersion, "version")
    version.status, version.extracted_text, version.error_code = (
        "extracted",
        "Saved synthetic text",
        "LOCAL_MODEL_MISSING",
    )
    old = Job(
        owner_id="teacher",
        course_id="course",
        kind="embed",
        status="failed",
        payload={"version_id": "version"},
    )
    session.add(old)
    session.flush()
    old.payload = {**old.payload, "_ai_provider": "ollama"}
    session.commit()
    ids = migrate_extracted_materials(session)
    session.commit()
    assert len(ids) == 1 and migrate_extracted_materials(session) == []
    new = session.get(Job, ids[0])
    assert new.status == "waiting_ai" and new.payload["_ai_provider"] == "gemini"
    assert new.payload["previous_provider_job_id"] == old.id
    assert old.status == "failed" and old.payload["_ai_provider"] == "ollama"
    assert version.extracted_text == "Saved synthetic text" and version.filename == "synthetic.txt"
    assert version.error_code == "GEMINI_CALLS_DISABLED"
    assert worker.run_once(new.id) is False and fake_provider == []


def test_paused_requests_never_fall_back_to_ollama(paused, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP request may run while Gemini is paused")

    import httpx

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    with pytest.raises(ValueError, match="GEMINI_CALLS_DISABLED"):
        retrieval.embed(["synthetic"])
    with pytest.raises(ValueError, match="GEMINI_CALLS_DISABLED"):
        worker.model_json("synthetic", {"type": "object"})


def test_loopback_guard_blocks_dns_and_direct_external_connections(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    monkeypatch.setattr(socket.socket, "connect", lambda *args: None)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *args: 0)
    guard_loopback()
    assert socket.getaddrinfo("127.0.0.1", 8100) == []
    with pytest.raises(PermissionError):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
    with socket.socket() as client:
        assert client.connect(("127.0.0.1", 8100)) is None
        for method in [client.connect, client.connect_ex]:
            with pytest.raises(PermissionError):
                method(("8.8.8.8", 443))


def test_separate_launcher_can_start_paused_api(paused, tmp_path, monkeypatch):
    _, _, config = paused
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets/app.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(
        config, "database_url", "postgresql+psycopg://synthetic:unused@127.0.0.1:55433/synthetic"
    )
    path = Path(__file__).resolve().parents[3] / "scripts/run_gemini_local.py"
    spec = importlib.util.spec_from_file_location("gemini_launcher_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", [str(path), "api", "--runtime-root", str(tmp_path)])
    import uvicorn
    from lerny import local_network

    calls = []
    monkeypatch.setattr(local_network, "guard_loopback", lambda: calls.append("guard"))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append("api"))
    for name in (
        "LERNY_RUNTIME_ROOT",
        "LERNY_DEPLOYMENT",
        "LERNY_AI_PROVIDER",
        "LERNY_GEMINI_CALLS_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    module.main()
    assert calls == ["guard", "api"]
