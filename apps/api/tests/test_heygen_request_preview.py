import copy
import json
import socket

import httpx
import pytest
import test_lecture_specs as intake_tests
from lerny import worker
from lerny.heygen_lecture_profile import LERNY_LOOK_ID, LERNY_VOICE_ID
from lerny.heygen_request_preview import ENDPOINT, PreviewOptions, compile_preview
from lerny.lecture_presentation import presentation_profile
from lerny.models import Job, Material
from lerny.security import COOKIE
from sqlalchemy import func, select
from test_lecture_grounding import seed_request, simulated_reviewer

api = intake_tests.api
spec = intake_tests.spec
context = intake_tests.context
prepare = intake_tests.prepare


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Request preview must not make network calls")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_compile_preserves_script_and_all_local_cues(spec, context):
    original = copy.deepcopy(spec)
    result = compile_preview(spec, context, PreviewOptions())
    assert (
        result["request_count"] == 1
        and result["preview_kind"] == "unverified_request_preview"
    )
    assert result["unresolved_fields"] == []
    assert not any(
        result[k]
        for k in (
            "submitted",
            "submission_allowed",
            "render_allowed",
            "publication_allowed",
        )
    )
    assert spec == original
    request = result["requests"][0]
    assert request["url"] == "https://api.heygen.com/v3/video-agents" == ENDPOINT
    assert request["method"] == "POST"
    assert request["headers"] == {"Content-Type": "application/json"}
    body = request["body"]
    assert set(body) == {
        "mode",
        "orientation",
        "avatar_id",
        "voice_id",
        "prompt",
        "visibility",
    }
    assert body["mode"] == "generate" and body["orientation"] == "landscape"
    assert body["avatar_id"] == LERNY_LOOK_ID
    assert body["voice_id"] == LERNY_VOICE_ID
    prompt = body["prompt"]
    assert result["prompt_characters"] == len(prompt) <= 10000
    assert "16:9" in prompt and "오른쪽" in prompt
    assert body["visibility"] == "private"
    assert "왼쪽에 계속 앉아" in prompt
    assert "화이트보드" not in prompt
    positions = []
    for scene, plan in zip(
        spec["scenes"], result["composition_plan"]["scenes"], strict=True
    ):
        assert plan["request_index"] == 0
        assert plan["script"] == "\n".join(u["text"] for u in scene["utterances"])
        assert plan["visual_events"] == scene["visual_events"]
        assert plan["gesture_cues"] == scene["gesture_cues"]
        assert plan["visual"] == scene["visual"]
        for u in plan["utterances"]:
            assert (
                plan["script"][u["character_start"] : u["character_end"]] == u["text"]
            )
            assert prompt.count(u["text"]) == 1
            positions.append(prompt.index(u["text"]))
    assert positions == sorted(positions)
    assert "source_refs" not in json.dumps(request)
    assert "src_stack_01" not in prompt
    assert "source_snapshot_id" not in prompt
    assert "pop block_30(값 30). 결과: 아래→위 [10, 20], TOP=20" in prompt
    assert "블록 30 (block_30) 방향" in prompt
    assert (
        "직전 스택을 지우지 않고 핵심 문구 옆에 유지: 아래→위 [10, 20], TOP=20"
        in prompt
    )
    plan = result["composition_plan"]
    assert plan["actual_duration_seconds"] is None
    assert plan["aspect_ratio"] == "16:9"
    assert "canvas" not in plan  # No unsupported pixel resolution promise.
    assert plan["layout"]["ratio_scope"] == "approximate_visual_emphasis"
    assert plan["layout"]["split_screen"] is False
    assert plan["layout"]["instructor_width_ratio"] == 0.4
    assert plan["layout"]["material_width_ratio"] == 0.6


def test_caller_choices_are_preserved_but_not_claimed_verified(spec, context):
    result = compile_preview(
        spec, context, PreviewOptions(avatar_id="chosen-look", voice_id="chosen-voice")
    )
    assert result["preview_kind"] == "unverified_request_preview"
    assert result["asset_verification"] == "not_checked"
    assert result["unresolved_fields"] == []
    assert result["requests"][0]["body"]["avatar_id"] == "chosen-look"
    assert result["requests"][0]["body"]["voice_id"] == "chosen-voice"
    assert not result["submission_allowed"]


def test_optional_style_preserves_content_without_enabling_submission(spec, context):
    baseline = compile_preview(spec, context, PreviewOptions())
    styled = compile_preview(spec, context, PreviewOptions(style_id="selected-style"))
    expected = {**baseline["requests"][0]["body"], "style_id": "selected-style"}
    assert styled["requests"][0]["body"] == expected
    assert styled["unresolved_fields"] == baseline["unresolved_fields"]
    assert not styled["submitted"] and not styled["submission_allowed"]


def test_prompt_derives_values_and_end_boundaries_from_input(spec, context):
    scene = spec["scenes"][1]
    scene["visual"]["elements"][2]["value"] = 47
    scene["visual_events"][3]["expected_value"] = 47
    scene["visual_events"][3]["trigger"]["boundary"] = "end"
    # JSON array order is not timeline order.
    scene["visual_events"].reverse()
    prompt = compile_preview(spec, context, PreviewOptions())["requests"][0]["body"][
        "prompt"
    ]
    assert "push block_30(값 47). 결과: 아래→위 [10, 20, 47], TOP=47" in prompt
    assert "화면 end: stack_main에 pop block_30(값 47)" in prompt
    assert "블록 47 (block_30) 방향" in prompt


def make_long_spec(spec):
    # Valid speech length, but visual copy makes the production prompt exceed 10k.
    spec["scenes"][0]["visual"]["key_points"] = ["가" * 1000] * 8
    spec["scenes"][2]["visual"]["key_points"] = ["나" * 1000] * 3


def test_oversize_prompt_rejected_without_truncation(spec, context):
    from lerny.heygen_request_preview import PromptTooLong

    make_long_spec(spec)
    with pytest.raises(PromptTooLong, match="VIDEO_AGENT_PROMPT_TOO_LONG"):
        compile_preview(spec, context, PreviewOptions())


def test_schema_and_failed_evidence_state_cannot_be_compiled(spec, context):
    spec["generation_status"] = "insufficient_evidence"
    with pytest.raises(ValueError, match="LECTURE_NOT_PREVIEWABLE"):
        compile_preview(spec, context, PreviewOptions())


def test_shared_handoff_examples_match_server_policy(spec):
    base = intake_tests.EXAMPLE.parent
    generation = json.loads(
        (base / "generation-input.example.json").read_text(encoding="utf-8")
    )
    expected = json.loads(
        (base / "heygen-preview.example.json").read_text(encoding="utf-8")
    )
    assert (
        generation["generation_input"]["presentation_profile"] == presentation_profile()
    )
    assert (
        compile_preview(spec, generation["generation_input"], PreviewOptions())
        == expected
    )
    changed = presentation_profile()
    changed["layout"]["instructor_width_ratio"] = 0.9
    assert presentation_profile()["layout"]["instructor_width_ratio"] == 0.4


def previewable(api, spec):
    client, _, _ = api
    base = prepare(api, spec)
    assert client.post(base + "/validate", json=spec).status_code == 200
    return base


def test_api_preview_has_no_job_or_spec_mutation(api, spec, monkeypatch):
    client, session, _ = api
    base = previewable(api, spec)
    before_count = session.scalar(select(func.count()).select_from(Job))
    before = copy.deepcopy(session.get(Job, spec["request_id"]).result)
    monkeypatch.setenv("HEYGEN_API_KEY", "DO_NOT_READ_OR_EXPOSE")
    response = client.post(base + "/heygen-preview", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["request_count"] == 1
    assert result["validation"]["grounding"]["semantic_grounding"] == "not_checked"
    assert "GROUNDING_NOT_COMPLETED" in result["blockers"]
    assert "DO_NOT_READ_OR_EXPOSE" not in response.text
    assert session.scalar(select(func.count()).select_from(Job)) == before_count
    assert session.get(Job, spec["request_id"], populate_existing=True).result == before
    assert client.post(base + "/heygen-preview", json={}).json() == result


@pytest.mark.parametrize(
    "body",
    [
        {"dry_run": False},
        {"submit": True},
        {"api_key": "secret"},
        {"spec": {}},
        {"render_allowed": True},
        {"avatar_id": ""},
        {"resolution": "4k"},
        {"resolution": "1080p"},
        {"aspect_ratio": "9:16"},
        {"layout": {"instructor_width_ratio": 0.5}},
        {"callback_url": "https://example.com"},
    ],
)
def test_reject_unsupported_options_or_submission_flags(api, spec, body):
    client, _, _ = api
    base = previewable(api, spec)
    assert client.post(base + "/heygen-preview", json=body).status_code == 422


@pytest.mark.parametrize("actor", ["student", "outsider", "anonymous", "bad_csrf"])
def test_access(api, spec, actor):
    client, _, tokens = api
    base = previewable(api, spec)
    if actor == "anonymous":
        client.cookies.clear()
    elif actor == "bad_csrf":
        client.headers["X-CSRF-Token"] = "wrong"
    else:
        client.cookies.set(COOKIE, tokens[actor][0])
        client.headers["X-CSRF-Token"] = tokens[actor][1]
    assert client.post(base + "/heygen-preview", json={}).status_code in {401, 403, 404}


def test_stale_source_rejected(api, spec):
    client, session, _ = api
    base = previewable(api, spec)
    session.get(Material, "material").visibility = "private"
    session.commit()
    assert client.post(base + "/heygen-preview", json={}).status_code == 409


def test_grounded_result_is_not_generation_approval(api, spec, monkeypatch):
    client, session, _ = api
    base, queued = seed_request(api, spec)
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", simulated_reviewer)
    worker.run_once(queued["job_id"])
    response = client.post(base + "/heygen-preview", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["validation"]["grounding"]["semantic_grounding"] == "model_supported"
    assert "HUMAN_REVIEW_REQUIRED" in data["blockers"]
    assert not data["submission_allowed"]
    spec["title"] = "변경된 대본 제목"
    assert client.post(base + "/validate", json=spec).status_code == 200
    assert (
        client.post(base + "/heygen-preview", json={}).json()["validation"][
            "grounding"
        ]["semantic_grounding"]
        == "not_checked"
    )


def test_known_contradiction_blocks_preview(api, spec, monkeypatch):
    client, session, _ = api
    base, queued = seed_request(api, spec)

    def reviewer(prompt, schema):
        result = simulated_reviewer(prompt, schema)
        result["items"][0]["verdict"] = "contradicted"
        return result

    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", reviewer)
    worker.run_once(queued["job_id"])
    assert client.post(base + "/heygen-preview", json={}).status_code == 409
    original = session.get(Job, queued["job_id"], populate_existing=True)
    session.add(
        Job(
            owner_id=original.owner_id,
            course_id=original.course_id,
            kind="lecture_grounding",
            status="queued",
            payload=dict(original.payload),
        )
    )
    session.commit()
    assert client.post(base + "/heygen-preview", json={}).status_code == 409


def test_api_reports_prompt_length_separately_from_structure(api, spec):
    make_long_spec(spec)
    base = previewable(api, spec)
    response = api[0].post(base + "/heygen-preview", json={})
    assert response.status_code == 422
    assert "10,000" in response.text
