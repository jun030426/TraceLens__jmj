"""Kind-derived purposes, index transitions, and source isolation; no external requests."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lerny import cloud_uploads, retrieval, worker
from lerny.config import settings
from lerny.learning import valid_sources
from lerny.lecture_specs import source_snapshot
from lerny.material_policy import KINDS, internal_use_for
from lerny.models import Job, Material, MaterialVersion, UploadIntent
from test_lecture_specs import api  # noqa: F401
from test_material_management import body, local  # noqa: F401


@pytest.fixture
def managed(local, monkeypatch):  # noqa: F811
    from lerny import operations
    # Queue policy uses the fixture database; worker telemetry has its own tests.
    monkeypatch.setattr(operations, 'finished', lambda *args: None)
    monkeypatch.setattr(settings(), "ai_provider", "gemini")
    monkeypatch.setattr(settings(), "gemini_calls_enabled", False)
    return local


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_upload_derives_purpose_and_ignores_old_client_toggle(managed, kind):
    client, session, _ = managed
    expected = internal_use_for(kind)
    response = client.post(
        "/api/v1/courses/course/materials",
        data={
            "kind": kind,
            "week": "6",
            "visibility": "private",
            "internal_use": "none" if expected == "validation_grading" else "validation_grading",
        },
        files={"file": ("synthetic.txt", b"Synthetic lecture or grading reference.", "text/plain")},
    )
    assert response.status_code == 201, response.text
    material = session.get(Material, response.json()["material_id"])
    assert material.internal_use == expected and material.visibility == "private"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_edit_kind_derives_purpose_and_protects_answers(managed, kind):
    client, session, _ = managed
    response = client.patch(
        "/api/v1/materials/material",
        headers={"If-Match": "1"},
        json=body(kind=kind, internal_use="none" if kind == "answer" else "validation_grading"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["internal_use"] == internal_use_for(kind)
    assert response.json()["visibility"] == ("private" if kind == "answer" else "public")
    assert session.get(MaterialVersion, "version").filename == "synthetic.txt"


def test_access_endpoint_cannot_reintroduce_manual_flag(managed):
    client, _, _ = managed
    response = client.patch(
        "/api/v1/materials/material/access",
        headers={"If-Match": "1"},
        json={"visibility": "private", "internal_use": "validation_grading"},
    )
    assert response.status_code == 200
    assert response.json()["internal_use"] == "none"
    assert response.json()["visibility"] == "private"


def test_legacy_lecture_correction_keeps_text_and_queues_index_while_paused(managed):
    client, session, _ = managed
    material = session.get(Material, "material")
    version = session.get(MaterialVersion, "version")
    material.internal_use = "validation_grading"
    version.extracted_text = "Synthetic original retained"
    session.commit()
    response = client.patch(
        "/api/v1/materials/material",
        headers={"If-Match": "1"},
        json={k: v for k, v in body().items() if k != "internal_use"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["internal_use"] == "none"
    assert response.json()["processing_status"] == "waiting_ai"
    assert response.json()["version"]["error_code"] == "GEMINI_CALLS_DISABLED"
    assert (
        version.extracted_text == "Synthetic original retained" and version.object_key == "unused"
    )
    job = session.scalar(select(Job).where(Job.kind == "embed"))
    assert job.payload["_ai_provider"] == "gemini" and job.attempt == 0
    assert worker.run_once(job.id) is False
    assert (
        client.patch(
            "/api/v1/materials/material", headers={"If-Match": "2"}, json=body()
        ).status_code
        == 200
    )
    assert len(list(session.scalars(select(Job).where(Job.kind == "embed")))) == 1


def test_reclassifying_pending_lecture_as_answer_does_not_call_provider(managed):
    client, session, _ = managed
    version = session.get(MaterialVersion, "version")
    version.status, version.extracted_text = "extracted", "Synthetic answer reference"
    job = Job(
        owner_id="teacher",
        course_id="course",
        kind="embed",
        status="waiting_ai",
        error_code="GEMINI_CALLS_DISABLED",
        payload={"version_id": "version"},
    )
    session.add(job)
    session.commit()
    result = client.patch(
        "/api/v1/materials/material", headers={"If-Match": "1"}, json=body(kind="answer")
    )
    assert result.status_code == 200
    assert result.json()["internal_use"] == "validation_grading"
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded" and version.status == "ready"
    assert session.scalar(select(Job).where(Job.kind == "auto_concepts")) is None


def test_private_lecture_stays_private_when_normalized(managed):
    client, session, _ = managed
    material = session.get(Material, "material")
    material.visibility, material.internal_use = "private", "validation_grading"
    session.get(MaterialVersion, "version").extracted_text = "Private lecture"
    session.commit()
    result = client.patch(
        "/api/v1/materials/material", headers={"If-Match": "1"}, json=body(visibility="private")
    )
    assert result.status_code == 200 and result.json()["internal_use"] == "none"
    assert material.visibility == "private"
    assert list(session.scalars(select(Job))) == []


@pytest.mark.parametrize("kind", ["lecture", "answer"])
def test_cloud_upload_metadata_uses_same_rule_without_storage_calls(managed, monkeypatch, kind):
    client, session, _ = managed
    monkeypatch.setattr(settings(), "deployment", "cloud")
    monkeypatch.setattr(settings(), "ai_provider", "ollama")
    monkeypatch.setattr(cloud_uploads, "now", datetime.now)
    monkeypatch.setattr(
        cloud_uploads.storage, "signed_upload", lambda key: "https://storage.invalid/synthetic"
    )
    content = b"Synthetic upload"
    monkeypatch.setattr(cloud_uploads.storage, "download", lambda *args: content)
    writes = []
    monkeypatch.setattr(cloud_uploads.storage, "put", lambda key, data: writes.append(data))
    response = client.post(
        "/api/v1/courses/course/uploads",
        json={
            "filename": "synthetic.txt",
            "size": len(content),
            "kind": kind,
            "visibility": "public",
            "internal_use": "none" if kind == "answer" else "validation_grading",
        },
    )
    assert response.status_code == 201, response.text
    intent = session.get(UploadIntent, response.json()["upload_id"])
    assert intent.metadata_["internal_use"] == internal_use_for(kind)
    assert intent.metadata_["visibility"] == ("private" if kind == "answer" else "public")
    # Old pending upload metadata is also normalized at completion.
    intent.metadata_ = {
        **intent.metadata_,
        "internal_use": "none" if kind == "answer" else "validation_grading",
        "visibility": "public",
    }
    session.commit()
    result = client.post(f"/api/v1/uploads/{intent.id}/complete")
    assert result.status_code == 201, result.text
    material = session.get(Material, result.json()["material_id"])
    assert material.internal_use == internal_use_for(kind) and material.visibility == ("private" if kind == "answer" else "public")
    assert writes == [content]


@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_answer_reference_never_becomes_public_generation_source(managed, monkeypatch, provider):
    _, session, _ = managed
    monkeypatch.setattr(settings(), "ai_provider", provider)
    material = session.get(Material, "material")
    material.kind, material.internal_use = "answer", "validation_grading"
    session.commit()
    assert retrieval.search_public(session, "course", "stack") == []
    assert source_snapshot(session, "course", "src_stack_01") == (None, None)
    question = SimpleNamespace(
        course_id="course",
        sources=[
            {
                "chunk_id": "src_stack_01",
                "quote": "Synthetic public stack rule 1",
            }
        ],
    )
    assert not valid_sources(session, question)


@pytest.mark.parametrize("selection", [{}, {"kind": None}, {"kind": ""}, {"kind": " "}, {"kind": "invalid"}])
def test_new_cloud_upload_requires_explicit_valid_kind_before_storage(managed, monkeypatch, selection):
    client, session, _ = managed
    monkeypatch.setattr(settings(), "deployment", "cloud")
    monkeypatch.setattr(cloud_uploads.storage, "signed_upload", lambda *args: pytest.fail("Unclassified upload reached Storage"))
    for filename in ["lecture.pptx", "example.py", "lecture.mp4"]:
        result = client.post("/api/v1/courses/course/uploads", json={"filename": filename, "size": 100, **selection})
        assert result.status_code == 422, result.text
    assert list(session.scalars(select(UploadIntent))) == []


@pytest.mark.parametrize("selection", [{}, {"kind": ""}])
def test_new_local_upload_requires_explicit_kind(managed, selection):
    client, session, _ = managed
    result = client.post("/api/v1/courses/course/materials", data={"week": "1", "visibility": "public", **selection},
                         files={"file": ("answer.txt", b"Synthetic answer", "text/plain")})
    assert result.status_code == 422, result.text
    assert len(list(session.scalars(select(Material)))) == 1


def test_cloud_file_replacement_preserves_answer_classification(managed, monkeypatch):
    client, session, _ = managed
    material = session.get(Material, "material")
    material.kind, material.visibility, material.internal_use = "answer", "private", "validation_grading"
    session.commit()
    monkeypatch.setattr(settings(), "deployment", "cloud")
    monkeypatch.setattr(cloud_uploads, "now", datetime.now)
    monkeypatch.setattr(cloud_uploads.storage, "signed_upload", lambda *args: "https://storage.invalid/synthetic")
    content = b"Replacement answer"
    monkeypatch.setattr(cloud_uploads.storage, "download", lambda *args: content)
    monkeypatch.setattr(cloud_uploads.storage, "put", lambda *args: None)
    prepared = client.post("/api/v1/courses/course/uploads", json={"filename": "answer.txt", "size": len(content),
                           "material_id": material.id, "revision": material.revision, "visibility": "public"})
    assert prepared.status_code == 201, prepared.text
    intent = session.get(UploadIntent, prepared.json()["upload_id"])
    assert intent.metadata_["kind"] == "answer" and intent.metadata_["visibility"] == "private"
    result = client.post(f"/api/v1/uploads/{intent.id}/complete")
    assert result.status_code == 201, result.text
    session.refresh(material)
    assert (material.kind, material.visibility, material.internal_use) == ("answer", "private", "validation_grading")
