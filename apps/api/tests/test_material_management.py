"""Material edits and recoverable extraction, using synthetic in-memory data only."""

import httpx
import pytest
from sqlalchemy import select

from lerny import inference, worker
from lerny.config import settings
from lerny.models import Chunk, Course, Job, Material, MaterialVersion, Section
from lerny.security import COOKIE
from test_lecture_specs import api  # noqa: F401


@pytest.fixture
def local(api, tmp_path, monkeypatch):  # noqa: F811
    client, session, tokens = api
    monkeypatch.setattr(settings(), "runtime_root", tmp_path)
    monkeypatch.setattr(settings(), "deployment", "local")
    monkeypatch.setattr(settings(), "ai_provider", "ollama")
    monkeypatch.setattr(worker, "engine", lambda: session.bind)
    monkeypatch.setattr(worker, "heartbeat", lambda *args: None)
    session.get(Material, "material").kind = "lecture"
    session.commit()
    return client, session, tokens


def body(**changes):
    return {
        "title": "synthetic",
        "week": 1,
        "kind": "lecture",
        "visibility": "public",
        "internal_use": "none",
        **changes,
    }


def test_edit_week_and_title_preserves_file_and_does_not_call_ai(local):
    client, session, _ = local
    original = session.get(MaterialVersion, "version")
    identity = (original.id, original.filename, original.sha256, original.object_key)
    epoch = session.get(Course, "course").access_epoch
    result = client.patch(
        "/api/v1/materials/material",
        json=body(week=6, title="6주차 스택"),
        headers={"If-Match": "1"},
    )
    assert result.status_code == 200, result.text
    assert (
        result.json()["week"],
        result.json()["title"],
        result.json()["revision"],
    ) == (6, "6주차 스택", 2)
    assert result.json()["active_version_id"] == "version"
    assert identity == (
        original.id,
        original.filename,
        original.sha256,
        original.object_key,
    )
    assert session.get(Course, "course").access_epoch == epoch + 1
    assert list(session.scalars(select(Job))) == []
    assert (
        client.patch(
            "/api/v1/materials/material",
            json=body(week=6, title="6주차 스택"),
            headers={"If-Match": "2"},
        ).json()["revision"]
        == 2
    )
    assert (
        client.patch(
            "/api/v1/materials/material", json=body(), headers={"If-Match": "1"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "changes", [{"week": 0}, {"week": 53}, {"title": "   "}, {"kind": "invalid"}]
)
def test_metadata_validation(local, changes):
    client, _, _ = local
    assert (
        client.patch(
            "/api/v1/materials/material",
            json=body(**changes),
            headers={"If-Match": "1"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("role", ["student", "outsider"])
def test_metadata_requires_course_staff(local, role):
    client, _, tokens = local
    client.cookies.set(COOKIE, tokens[role][0])
    client.headers["X-CSRF-Token"] = tokens[role][1]
    assert (
        client.patch(
            "/api/v1/materials/material", json=body(week=6), headers={"If-Match": "1"}
        ).status_code
        == 404
    )


def test_week_edit_updates_auto_progress_without_changing_manual_progress(local):
    client, session, _ = local
    session.get(MaterialVersion, "version").concept_ids = ["concept_stack"]
    for mode in ("auto", "manual"):
        session.add(
            Section(
                id=mode,
                course_id="course",
                title=mode,
                progress_mode=mode,
                progress=["concept_stack"],
                week_schedule=[{"week": 1, "date": "2000-01-01"}],
            )
        )
    session.commit()
    result = client.patch(
        "/api/v1/materials/material", json=body(week=6), headers={"If-Match": "1"}
    )
    assert result.status_code == 200, result.text
    assert session.get(Section, "auto").progress == []
    assert session.get(Section, "manual").progress == ["concept_stack"]


def upload(client, visibility="public", internal_use="none"):
    original = "Synthetic stack: push adds an item; pop removes the last item."
    result = client.post(
        "/api/v1/courses/course/materials",
        data={
            "kind": "lecture",
            "week": 1,
            "visibility": visibility,
            "internal_use": internal_use,
        },
        files={"file": ("lecture.txt", original.encode(), "text/plain")},
    )
    assert result.status_code == 201, result.text
    return result.json(), original


def test_failed_embedding_preserves_extracted_text_and_can_retry(local, monkeypatch):
    client, session, _ = local
    item, original = upload(client)

    def missing(_):
        raise ValueError("LOCAL_MODEL_MISSING")

    monkeypatch.setattr(worker, "embed", missing)
    assert worker.run_once(item["processing_job_id"])
    session.expire_all()
    version = session.get(MaterialVersion, item["version_id"])
    assert version.status == "extracted" and version.extracted_text == original
    job = session.scalar(select(Job).where(Job.kind == "embed"))
    assert job is not None and worker.run_once(job.id)
    session.expire_all()
    assert job.status == "failed" and version.status == "extracted"
    assert (
        version.error_code == "LOCAL_MODEL_MISSING"
        and version.extracted_text == original
    )
    assert (
        session.scalar(select(Chunk).where(Chunk.version_id == version.id)).content
        == original
    )
    material = next(
        m
        for m in client.get("/api/v1/courses/course/materials").json()["items"]
        if m["id"] == item["material_id"]
    )
    assert (material["processing_stage"], material["processing_status"]) == (
        "embed",
        "failed",
    )
    assert (
        client.get(f"/api/v1/materials/{item['material_id']}/transcript").json()["text"]
        == original
    )
    assert (
        client.get(f"/api/v1/materials/{item['material_id']}/file").content
        == original.encode()
    )
    monkeypatch.setattr(worker, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    assert client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 202
    assert worker.run_once(job.id)
    session.expire_all()
    assert version.status == "ready" and version.error_code is None
    assert session.get(Material, item["material_id"]).active_version_id == version.id
    assert (
        client.get(f"/api/v1/materials/{item['material_id']}/file").content
        == original.encode()
    )


def test_private_text_storage_does_not_require_ai(local):
    client, session, _ = local
    item, original = upload(client, "private")
    assert worker.run_once(item["processing_job_id"])
    session.expire_all()
    version = session.get(MaterialVersion, item["version_id"])
    assert version.status == "extracted" and version.extracted_text == original
    assert (
        list(
            session.scalars(
                select(Job).where(Job.kind.in_(["auto_concepts", "questions"]))
            )
        )
        == []
    )


def test_model_404_has_actionable_error(local, monkeypatch):
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda _, url, **kwargs: httpx.Response(
            404, request=httpx.Request("POST", url), json={"error": "not found"}
        ),
    )
    with pytest.raises(ValueError, match="^LOCAL_MODEL_MISSING$"):
        inference.perform("embed", {"input": "synthetic"})


@pytest.mark.parametrize("available", [False, True])
def test_ai_status_checks_model_presence(local, monkeypatch, available):
    client, _, _ = local
    models = [settings().model_name, worker.EMBED_MODEL] if available else []
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda _, url, **kwargs: httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"models": [{"name": m} for m in models]},
        ),
    )
    # Call the TestClient implementation directly; its base HTTP client's get is patched above.
    result = client.request("GET", "/api/v1/ai/status")
    assert result.status_code == 200
    assert result.json()["status"] == ("local" if available else "offline")
    if not available:
        assert result.json()["reason"] == "LOCAL_MODEL_MISSING"
