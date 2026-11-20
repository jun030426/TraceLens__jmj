import copy
import io
import json

import httpx
import pytest
from lerny import video_worker
from lerny.heygen_lecture_profile import LERNY_LOOK_ID, LERNY_VOICE_ID
from lerny.heygen_site_video import (
    SiteVideoPlan,
    card_image,
    checked_request,
    compile_site_plan,
    prepare_request,
    presentation_settings,
    scene_scripts,
)
from lerny.heygen_slides import compile_studio
from PIL import Image


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    monkeypatch.setattr(video_worker.settings(), 'heygen_rendering_enabled', True)
    def forbidden(*args, **kwargs):
        raise AssertionError("Only explicit MockTransport is allowed")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


def lesson():
    return {"title": "스택과 push", "narration": [
        "스택은 후입선출 구조입니다. 맨 위에 데이터를 추가하는 연산은 push입니다.",
        "빈 스택에 2, 5, 8을 차례로 넣으면 맨 위는 8입니다."],
        "key_facts": ["스택은 후입선출 구조입니다."], "target_duration_seconds": 50}


def studio():
    return compile_studio("스택", ["test-card"], ["스택은 후입선출입니다."])


def test_plan_is_offline_and_cannot_change_avatar_or_model():
    data = lesson()
    original = copy.deepcopy(data)
    plan = compile_site_plan(data)
    assert data == original and plan["lesson"]["key_facts"] == data["key_facts"]
    assert presentation_settings()["motion_prompt_applied"] is False
    with pytest.raises(ValueError):
        SiteVideoPlan.model_validate({**plan, "avatar_id": "another"})
    with pytest.raises(ValueError):
        compile_site_plan({**data, "narration": ["a" * 3000] * 30})


def test_long_narration_preserved_without_truncation():
    data = lesson()
    data["narration"] = [("스택의 맨 위에 추가합니다. " * 40) + "마지막 문장입니다."]
    scripts = scene_scripts(SiteVideoPlan.model_validate(compile_site_plan(data)).lesson)
    assert "".join(scripts) == data["narration"][0]
    assert len(scripts) > 1


def test_preparation_uploads_cards_but_never_creates_video():
    uploads = []
    def provider(req):
        assert req.method == "POST" and req.url.path == "/v3/assets"
        uploads.append(req)
        return httpx.Response(200, json={"data": {"asset_id": f"card-{len(uploads)}"}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        request = prepare_request(compile_site_plan(lesson()), client)
    assert len(uploads) == 2
    assert request["type"] == "studio" and request["resolution"] == "1080p"
    assert request["caption"] == {"file_format": "srt", "style": "default"}
    assert checked_request(request) == request
    for index, scene in enumerate(request["scenes"]):
        avatar = scene["input"]
        assert avatar["script"] == lesson()["narration"][index]
        assert avatar["avatar_id"] == LERNY_LOOK_ID and avatar["voice_id"] == LERNY_VOICE_ID
        assert avatar["engine"] == {"type": "avatar_v", "more_blinking": False}
        assert "expressiveness" not in avatar and "motion_prompt" not in avatar


def test_card_dimensions_and_layout_overflow_fail_before_network():
    with Image.open(io.BytesIO(card_image("스택", "맨 위의 값을 꺼냅니다.", 1, 1))) as picture:
        assert picture.size == (1920, 1080)
    with pytest.raises(ValueError, match="VIDEO_CARD_TEXT_OVERFLOW"):
        card_image("가" * 200, "나" * 180, 1, 1)


@pytest.mark.parametrize("field,value", [("avatar_id", "another"), ("voice_id", "another"),
    ("engine", {"type": "avatar_v"}), ("motion_prompt", "unsupported"), ("expressiveness", "low")])
def test_no_fallback_or_unsupported_motion(field, value):
    body = studio()
    body["scenes"][0]["input"][field] = value
    with pytest.raises(ValueError):
        checked_request(body)


def test_direct_submit_persists_before_post_and_only_once(monkeypatch):
    events, updates = [], []
    body = studio()
    monkeypatch.setattr(video_worker, "persist_prepared", lambda item, payload: events.append("saved") or True)
    monkeypatch.setattr(video_worker, "update", lambda item, **values: updates.append(values))
    def provider(req):
        events.append("post")
        assert req.method == "POST" and req.url.path == "/v3/videos"
        assert json.loads(req.content) == body
        return httpx.Response(200, json={"data": {"video_id": "video-one"}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process({"action": "submit", "request": body}, client)
    assert events == ["saved", "post"]
    assert updates[0]["provider_video_id"] == "video-one"
    assert "provider_session_id" not in updates[0]


def test_lost_lease_cannot_submit(monkeypatch):
    monkeypatch.setattr(video_worker, "persist_prepared", lambda *args: False)
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No render"))) as client:
        video_worker.process({"action": "submit", "request": studio()}, client)


@pytest.mark.parametrize("body", [{"mode": "generate", "prompt": "old Agent request"}, {}])
def test_old_or_invalid_request_is_held_without_render(monkeypatch, body):
    updates = []
    monkeypatch.setattr(video_worker, "update", lambda item, **v: updates.append(v))
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No render"))) as client:
        video_worker.process({"action": "submit", "request": body}, client)
    assert updates == [{"status": "held", "error_code": "VIDEO_PROFILE_REVIEW_REQUIRED"}]


@pytest.mark.parametrize("action", ["poll", "submit"])
def test_direct_receipt_never_resubmitted_or_polled_as_agent(monkeypatch, action):
    seen, updates = [], []
    monkeypatch.setattr(video_worker, "update", lambda item, **v: updates.append(v))
    def provider(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={"data": {"status": "processing"}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process({"action": action, "video_id": "receipt", "session_id": None}, client)
    assert seen == [("GET", "/v3/videos/receipt")]
    assert updates[0]["provider_video_id"] == "receipt"


def test_historical_agent_receipt_keeps_existing_poll_path(monkeypatch):
    seen = []
    monkeypatch.setattr(video_worker, "update", lambda *a, **k: None)
    def provider(req):
        seen.append((req.method, req.url.path))
        data = ({"session_id": "old", "video_id": "old-video", "status": "generating"}
                if req.url.path.endswith("/old") else {"status": "processing"})
        return httpx.Response(200, json={"data": data})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process({"action": "poll", "video_id": "old-video", "session_id": "old"}, client)
    assert seen == [("GET", "/v3/video-agents/old"), ("GET", "/v3/videos/old-video")]


@pytest.mark.parametrize("resolution,engine,voice,expected", [
    ("1080p", "avatar_v", LERNY_VOICE_ID, True), ("720p", "avatar_v", LERNY_VOICE_ID, False),
    ("1080p", "avatar_iv", LERNY_VOICE_ID, False), ("1080p", "avatar_v", "changed", False)])
def test_actual_render_engine_resolution_and_voice_verified(resolution, engine, voice, expected):
    data = {"video": {"resolution": resolution}, "scenes": [{
        "elements": [{"type": "avatar", "engine": engine, "avatar_id": LERNY_LOOK_ID}],
        "script": [{"type": "text", "voice_id": voice}]}]}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data}))) as client:
        assert video_worker.render_matches(client, "receipt") is expected


def test_mismatch_held_without_automatic_regeneration(monkeypatch):
    updates, seen = [], []
    monkeypatch.setattr(video_worker, "update", lambda item, **v: updates.append(v))
    monkeypatch.setattr(video_worker, "render_matches", lambda *args: False)
    def provider(req):
        seen.append(req.method)
        return httpx.Response(200, json={"data": {"status": "completed"}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process({"action": "poll", "video_id": "receipt", "session_id": None}, client)
    assert seen == ["GET"]
    assert updates == [{"status": "held", "provider_video_id": "receipt", "error_code": "VIDEO_RENDER_PROFILE_MISMATCH"}]
