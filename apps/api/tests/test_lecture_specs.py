import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from lerny.db import db
from lerny.lecture_contract import LectureSpec, validate_spec
from lerny.main import create_app
from lerny.models import Base, Chunk, Concept, Course, Job, Material, MaterialVersion, Term, User
from lerny.security import COOKIE, create_session
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

EXAMPLE = Path(__file__).resolve().parents[3] / "docs/contracts/lecture.example.json"


@pytest.fixture
def spec():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def context(spec):
    return {
        **{
            k: spec[k]
            for k in (
                "request_id",
                "concept_id",
                "concept_revision",
                "source_snapshot_id",
                "language",
                "learning_objective",
                "target_duration_seconds",
            )
        },
        "allowed_source_ids": ["src_stack_01", "src_stack_02"],
        "allowed_concept_ids": ["concept_stack"],
        "allow_generated_examples": True,
    }


def test_valid_example_never_authorizes_render(spec, context):
    parsed, result = validate_spec(spec, context)
    assert parsed is not None
    assert result["status"] == "needs_content_review"
    assert result["errors"] == []
    assert not result["render_allowed"] and not result["publication_allowed"]
    assert result["semantic_grounding"] == "not_checked"
    assert result["question_response_mode"] == "text_only"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda d: d.update(avatar_id="not-allowed"), "SCHEMA_INVALID"),
        (lambda d: d.update(presentation_profile={"aspect_ratio": "16:9"}), "SCHEMA_INVALID"),
        (lambda d: d.update(concept_revision="1"), "SCHEMA_INVALID"),
        (lambda d: d.update(concept_revision=True), "SCHEMA_INVALID"),
        (lambda d: d.update(request_id="other"), "REQUEST_MISMATCH"),
        (lambda d: d.update(source_snapshot_id="other"), "REQUEST_MISMATCH"),
        (lambda d: d.update(scenes=[]), "EMPTY_DRAFT"),
        (lambda d: d.update(generation_status="insufficient_evidence"), "INVALID_FAILURE_STATE"),
        (lambda d: d["scenes"][1]["utterances"][0].update(source_refs=[]), "MISSING_EVIDENCE"),
        (
            lambda d: d["scenes"][1]["utterances"][0].update(source_refs=["secret"]),
            "UNKNOWN_SOURCE",
        ),
        (lambda d: d["scenes"][1]["utterances"][0].update(utterance_id="u01"), "DUPLICATE_ID"),
        (lambda d: d["scenes"][1].pop("example_provenance"), "MISSING_EXAMPLE_PROVENANCE"),
        (
            lambda d: d["scenes"][1]["visual_events"][3].update(expected_value=20),
            "POP_VALUE_MISMATCH",
        ),
        (lambda d: d["scenes"][1]["visual_events"][3].update(element_id="block_10"), "INVALID_POP"),
        (
            lambda d: d["scenes"][1]["visual_events"][0].update(container_id="wrong"),
            "UNKNOWN_EVENT_TARGET",
        ),
        (
            lambda d: d["scenes"][1]["visual_events"][0]["trigger"].update(utterance_id="no"),
            "UNKNOWN_UTTERANCE",
        ),
        (
            lambda d: d["scenes"][1]["gesture_cues"][0].update(utterance_id="u06"),
            "GESTURE_TARGET_NOT_VISIBLE",
        ),
        (lambda d: d["learning_links"].update(related_concept_ids=["other"]), "UNKNOWN_CONCEPT"),
    ],
)
def test_reject_invalid_contract(spec, context, mutation, code):
    mutation(spec)
    _, result = validate_spec(spec, context)
    assert result["status"] == "rejected"
    assert code in {e["code"] for e in result["errors"]}


def test_examples_need_server_permission(spec, context):
    context["allow_generated_examples"] = False
    assert validate_spec(spec, context)[1]["status"] == "rejected"


def test_schema_error_identifies_known_field_without_returning_value(spec, context):
    spec["concept_revision"] = "PRIVATE_VALUE"
    error = validate_spec(spec, context)[1]["errors"][0]
    assert error["path"] == "concept_revision"
    assert "PRIVATE_VALUE" not in json.dumps(error)


def test_hold_insufficient_evidence(spec, context):
    spec.update(
        generation_status="insufficient_evidence",
        scenes=[],
        issues=[
            {
                "code": "insufficient_evidence",
                "message": "자료 부족",
                "source_refs": [],
                "affected_utterance_ids": [],
            }
        ],
    )
    result = validate_spec(spec, context)[1]
    assert result["structure_valid"] and result["status"] == "held"
    assert not result["render_allowed"]


def test_boundary_order_and_empty_pop(spec, context):
    scene = spec["scenes"][1]
    scene["gesture_cues"][0]["utterance_id"] = "u06"
    scene["visual_events"][3]["trigger"]["boundary"] = "end"
    assert validate_spec(spec, context)[1]["structure_valid"]
    scene["visual_events"][3]["trigger"] = {"utterance_id": "u02", "boundary": "start"}
    scene["visual_events"] = [scene["visual_events"][3]]
    assert "INVALID_POP" in {e["code"] for e in validate_spec(spec, context)[1]["errors"]}


def test_initial_state_duplicate_push_and_schema_export(spec, context):
    spec["scenes"][1]["visual"]["initial_state"]["items_bottom_to_top"] = ["block_10"]
    assert "DUPLICATE_PUSH" in {e["code"] for e in validate_spec(spec, context)[1]["errors"]}
    schema = json.loads((EXAMPLE.parent / "lecture-spec.schema.json").read_text(encoding="utf-8"))
    assert schema == LectureSpec.model_json_schema()


@pytest.fixture
def api(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("External HTTP must never run during lecture intake")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        teacher = User(
            id="teacher",
            login_id="teacher",
            display_name="teacher",
            password_hash="unused",
            role="teacher",
        )
        student = User(
            id="student",
            login_id="student",
            display_name="student",
            password_hash="unused",
            role="student",
        )
        outsider = User(
            id="outsider",
            login_id="outsider",
            display_name="other",
            password_hash="unused",
            role="teacher",
        )
        session.add_all(
            [
                teacher,
                student,
                outsider,
                Term(
                    id="term", name="term", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31)
                ),
            ]
        )
        session.flush()
        session.add(
            Course(
                id="course",
                term_id="term",
                title="course",
                lead_teacher_id="teacher",
                teaching_language="python",
            )
        )
        session.add(Concept(id="concept_stack", course_id="course", name="stack"))
        session.add(
            Material(
                id="material",
                course_id="course",
                title="synthetic",
                kind="pdf",
                week=1,
                visibility="public",
                active_version_id="version",
            )
        )
        session.flush()
        session.add(
            MaterialVersion(
                id="version",
                material_id="material",
                version_no=1,
                filename="synthetic.txt",
                object_key="unused",
                sha256="a" * 64,
                status="ready",
            )
        )
        session.flush()
        for i in (1, 2):
            session.add(
                Chunk(
                    id=f"src_stack_0{i}",
                    version_id="version",
                    content=f"Synthetic public stack rule {i}",
                    locator={"page": i},
                )
            )
        tokens = {u.id: create_session(session, u) for u in (teacher, student, outsider)}
        session.commit()
        app = create_app()

        def override_db():
            yield session

        app.dependency_overrides[db] = override_db
        with TestClient(app) as client:
            client.cookies.set(COOKIE, tokens["teacher"][0])
            client.headers["X-CSRF-Token"] = tokens["teacher"][1]
            yield client, session, tokens
    engine.dispose()


def prepare(api, spec):
    client, _session, _ = api
    response = client.post(
        "/api/v1/courses/course/lecture-spec-requests",
        json={
            "concept_id": "concept_stack",
            "chunk_ids": ["src_stack_01", "src_stack_02"],
            "learning_objective": spec["learning_objective"],
            "allow_generated_examples": True,
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    profile = data["generation_input"]["presentation_profile"]
    assert profile["aspect_ratio"] == "16:9"
    assert profile["layout"]["instructor_width_ratio"] == 0.4
    assert profile["layout"]["material_width_ratio"] == 0.6
    assert _session.get(Job, data["request_id"]).payload["presentation_profile"] == profile
    for key in ("request_id", "source_snapshot_id"):
        spec[key] = data["generation_input"][key]
    base = f"/api/v1/courses/course/lecture-spec-requests/{data['request_id']}"
    return base


def test_authenticated_round_trip_and_no_queue(api, spec):
    client, session, _ = api
    base = prepare(api, spec)
    response = client.post(base + "/validate", json=spec)
    assert response.status_code == 200, response.text
    assert response.json()["validation"]["status"] == "needs_content_review"
    assert client.get(base).json()["result"]["spec"] == spec
    job = session.get(Job, spec["request_id"])
    assert job.status == "checked" and job.attempt == 0 and job.lease_token is None
    assert client.get("/api/v1/jobs/" + job.id).status_code == 404
    job.status = "failed"
    session.commit()
    assert client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 409


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: setattr(s.get(Material, "material"), "visibility", "private"),
        lambda s: setattr(s.get(Material, "material"), "active_version_id", None),
        lambda s: setattr(s.get(Material, "material"), "deleted", True),
        lambda s: setattr(s.get(Material, "material"), "revision", 2),
        lambda s: setattr(s.get(Material, "material"), "course_id", "other-course"),
        lambda s: setattr(s.get(MaterialVersion, "version"), "status", "failed"),
        lambda s: setattr(s.get(Chunk, "src_stack_01"), "content", "Changed"),
        lambda s: setattr(s.get(Concept, "concept_stack"), "revision", 2),
        lambda s: setattr(s.get(Course, "course"), "access_epoch", 2),
    ],
)
def test_stale_snapshot_blocks_read_and_resubmit(api, spec, mutation):
    client, session, _ = api
    base = prepare(api, spec)
    assert client.post(base + "/validate", json=spec).status_code == 200
    mutation(session)
    session.commit()
    assert client.get(base).status_code == 409
    assert client.get(base).json()["spec"] is None
    assert client.post(base + "/validate", json=spec).status_code == 409


@pytest.mark.parametrize("actor", ["student", "outsider", "anonymous", "bad_csrf"])
def test_auth_and_csrf(api, spec, actor):
    client, _, tokens = api
    base = prepare(api, spec)
    if actor == "anonymous":
        client.cookies.clear()
    elif actor == "bad_csrf":
        client.headers["X-CSRF-Token"] = "bad"
    else:
        client.cookies.set(COOKIE, tokens[actor][0])
        client.headers["X-CSRF-Token"] = tokens[actor][1]
    assert client.post(base + "/validate", json=spec).status_code in (401, 403, 404)
    if actor != "bad_csrf":
        assert client.get(base).status_code in (401, 404)


def test_private_source_cannot_enter_request(api, spec):
    client, session, _ = api
    session.get(Material, "material").visibility = "private"
    session.commit()
    response = client.post(
        "/api/v1/courses/course/lecture-spec-requests",
        json={
            "concept_id": "concept_stack",
            "chunk_ids": ["src_stack_01"],
            "learning_objective": "스택 설명",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "raw,status",
    [
        ('{"a":1,"a":2}', 400),
        ('{"a":NaN}', 400),
        ("{", 400),
        ("[]", 422),
        ('"' + "a" * 262144 + '"', 413),
    ],
    ids=["duplicate_keys", "nan", "malformed", "array", "oversized"],
)
def test_untrusted_json(api, spec, raw, status):
    client, _, _ = api
    base = prepare(api, spec)
    response = client.post(base + "/validate", content=raw)
    assert response.status_code == status
    assert "render_allowed" not in response.json() or not response.json()["render_allowed"]


def test_bad_resubmission_clears_valid_result_without_echoing_unknown_values(api, spec):
    client, _, _ = api
    base = prepare(api, spec)
    assert client.post(base + "/validate", json=spec).status_code == 200
    bad = copy.deepcopy(spec)
    bad["TOP_SECRET_KEY"] = "TOP_SECRET_VALUE"
    response = client.post(base + "/validate", json=bad)
    assert response.status_code == 422
    assert "TOP_SECRET" not in response.text
    assert client.get(base).json()["result"]["spec"] is None


def test_worker_never_dispatches_lecture_even_if_status_is_queued(api, spec, monkeypatch):
    from lerny import worker

    _, session, _ = api
    prepare(api, spec)
    job = session.get(Job, spec["request_id"])
    job.status = "queued"
    session.commit()
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    assert worker.run_once(job.id) is False
    assert worker.run_once() is False
