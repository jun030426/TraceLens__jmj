import hashlib
import json

import httpx
import pytest
import test_heygen_pilot as pilot_tests
from lerny.heygen_video_agent import RunState, VideoAgentRun
from lerny.lecture_playback import LocalLecture, PlaybackError
from lerny.security import current_user

MP4 = pilot_tests.MP4
playback = pilot_tests.playback


@pytest.fixture(autouse=True)
def no_provider_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Playback must not call a provider")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(VideoAgentRun, "start", forbidden)
    monkeypatch.setattr(VideoAgentRun, "poll", forbidden)


def bind_test(playback):
    browser, _app, session, pilot = playback
    runtime = pilot.root.parent.parent
    selected = LocalLecture(runtime, "section1")
    selected.bind(title="스택 테스트", script="대본", test_video=pilot.video)
    return browser, session, selected


def test_test_file_range_head_authorization_and_metadata(playback):
    browser, session, _selected = bind_test(playback)
    base = "/api/v1/sections/section1/lecture-preview"
    data = browser.get(base).json()
    assert data["source_type"] == "local_test_video"
    assert data["title"] == "스택 테스트" and data["script"] == "대본"
    assert "runtime" not in json.dumps(data) and "session_id" not in data
    assert data["video_url"].startswith(base + "/file?v=")
    assert browser.get(data["video_url"]).content == MP4
    partial = browser.get(data["video_url"], headers={"Range": "bytes=4-11"})
    assert partial.status_code == 206 and partial.content == MP4[4:12]
    assert partial.headers["cache-control"] == "no-store"
    assert browser.get(data["video_url"], headers={"Range": "bytes=999999-"}).status_code == 416
    head = browser.head(data["video_url"])
    assert head.status_code == 200 and not head.content
    assert int(head.headers["content-length"]) == len(MP4)
    assert browser.get(base + "/file?v=old").status_code == 404
    session.scalar = lambda *args: None
    assert browser.get(data["video_url"]).status_code == 404
    assert browser.head(data["video_url"]).status_code == 404
    playback[1].dependency_overrides.pop(current_user)
    assert browser.get(base).status_code == 401
    assert browser.get(data["video_url"]).status_code == 401


def test_bound_file_missing_or_corrupt_does_not_fall_back_to_old_pilot(playback):
    browser, _, selected = bind_test(playback)
    base = "/api/v1/sections/section1/lecture-preview"
    selected.media(selected.read()).unlink()
    assert browser.get(base).json()["status"] == "storage_missing"
    assert browser.get(base + "/file").status_code == 404
    selected.manifest.write_text("broken", encoding="utf-8")
    assert browser.get(base).status_code == 503
    assert browser.get(base + "/file").status_code == 404


def test_completed_video_agent_file_is_read_only_and_section_bound(playback):
    browser, _, _, pilot = playback
    runtime = pilot.root.parent.parent
    run = VideoAgentRun(runtime / "data/heygen-video-agent/test-run")
    run.root.mkdir(parents=True)
    run.video.write_bytes(MP4)
    state = RunState(
        status="processing", fingerprint="a" * 64, session_id="test-session", video_id="test-video"
    )
    run.save(state)
    selected = LocalLecture(runtime, "section1")
    with pytest.raises(PlaybackError, match="VIDEO_NOT_COMPLETED"):
        selected.bind(title="강의", run_id="test-run")
    state.status, state.bytes, state.sha256 = "completed", len(MP4), hashlib.sha256(MP4).hexdigest()
    run.save(state)
    selected.bind(title="화이트보드 샘플", run_id="test-run")
    before = run.state_file.read_bytes()
    data = browser.get("/api/v1/sections/section1/lecture-preview").json()
    assert data["source_type"] == "video_agent" and data["status"] == "completed"
    assert "test-session" not in json.dumps(data) and "test-run" not in json.dumps(data)
    assert browser.get(data["video_url"], headers={"Range": "bytes=0-11"}).content == MP4[:12]
    assert run.state_file.read_bytes() == before
    assert LocalLecture(runtime, "section2").read() is None
    run.video.write_bytes(b"missing content")
    assert browser.get(data["video_url"]).status_code == 404


def test_binding_input_path_and_hash_checks(playback):
    _, _, _, pilot = playback
    runtime = pilot.root.parent.parent
    with pytest.raises(PlaybackError, match="INVALID_LOCAL_ID"):
        LocalLecture(runtime, "../secrets")
    selected = LocalLecture(runtime, "section1")
    with pytest.raises(PlaybackError, match="INVALID_LOCAL_ID"):
        selected.bind(title="test", run_id="../heygen-pilot")
    selected.bind(title="test", test_video=pilot.video)
    with pytest.raises(PlaybackError, match="BINDING_EXISTS"):
        selected.bind(title="new", test_video=pilot.video)
    selected.bind(title="new", test_video=pilot.video, replace=True)
    assert selected.status()["title"] == "new"
