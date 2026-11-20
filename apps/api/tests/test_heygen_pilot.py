import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from lerny import lecture_preview
from lerny.db import db
from lerny.heygen_pilot import Pilot, PilotError, job_lock, load_credentials
from lerny.main import create_app
from lerny.security import current_user

MP4 = b"\x00\x00\x00\x18ftypisom" + b"test-fixture-not-a-playable-video"


def client(handler):
    return httpx.Client(
        base_url="https://api.heygen.com",
        transport=httpx.MockTransport(handler),
        headers={"X-Api-Key": "test-secret"},
    )


def test_generate_resume_download_is_one_paid_call(tmp_path):
    calls = []
    statuses = iter(["processing", "completed"])

    def provider(request):
        calls.append(request.method)
        if request.method == "POST":
            assert Pilot(tmp_path).read()["status"] == "submitting"
            body = json.loads(request.content)
            assert body["aspect_ratio"] == "16:9"
            assert body["avatar_id"] == "avatar"
            assert "사과" in body["script"]
            return httpx.Response(200, json={"data": {"video_id": "video-1"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "status": next(statuses),
                    "video_url": "https://resource.heygen.ai/sample.mp4",
                }
            },
        )

    def media(request):
        assert "x-api-key" not in request.headers
        return httpx.Response(200, content=MP4)

    with client(provider) as api, httpx.Client(transport=httpx.MockTransport(media)) as download:
        first = Pilot(tmp_path)
        first.start(api, "avatar", "voice")
        assert first.poll(api, download) == "processing"
        resumed = Pilot(tmp_path)
        resumed.start(api, "avatar", "voice")
        assert resumed.poll(api, download) == "completed"
        assert resumed.poll(api, download) == "completed"
        assert calls == ["POST", "GET", "GET"]
        assert resumed.video.read_bytes() == MP4
        assert "video_url" not in resumed.read()
        assert "test-secret" not in (tmp_path / "job.json").read_text()
        with pytest.raises(PilotError, match="설정이 다릅니다"):
            resumed.start(api, "changed-avatar", "voice")


def test_ambiguous_submission_never_resubmits_and_can_recover(tmp_path):
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("provider-key-must-not-leak", request=request)

    with client(timeout) as api:
        pilot = Pilot(tmp_path)
        with pytest.raises(PilotError, match="접수를 확인하지"):
            pilot.start(api, "avatar", "voice")
        assert pilot.read()["status"] == "needs_attention"
        with pytest.raises(PilotError, match="재생성하지"):
            Pilot(tmp_path).start(api, "avatar", "voice")
        assert len(calls) == 1
        pilot.attach_video("verified-video-id")
        assert pilot.read()["video_id"] == "verified-video-id"


def test_failed_download_resumes_without_regeneration(tmp_path):
    pilot = Pilot(tmp_path)
    pilot.save({"status": "processing", "video_id": "v1"})
    with (
        client(
            lambda r: httpx.Response(
                200,
                json={
                    "data": {
                        "status": "completed",
                        "video_url": "https://resource.heygen.ai/test.mp4",
                    }
                },
            )
        ) as api,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"<html>error</html>")
            )
        ) as media,
        pytest.raises(PilotError, match="MP4"),
    ):
        pilot.poll(api, media)
    assert pilot.status()["status"] == "storing"
    assert not pilot.video.exists()
    assert not (tmp_path / "sample.mp4.part").exists()
    with (
        client(
            lambda r: httpx.Response(
                200,
                json={
                    "data": {
                        "status": "completed",
                        "video_url": "https://resource.heygen.ai/test.mp4",
                    }
                },
            )
        ) as api,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=MP4))
        ) as media,
    ):
        assert pilot.poll(api, media) == "completed"


def test_download_rejects_untrusted_redirect(tmp_path):
    requests = []

    def redirect(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secrets"})

    with (
        httpx.Client(transport=httpx.MockTransport(redirect)) as media,
        pytest.raises(PilotError, match="다운로드 주소"),
    ):
        Pilot(tmp_path).download(media, "https://resource.heygen.ai/test.mp4")
    assert len(requests) == 1


def test_provider_failure_is_not_reported_as_ready(tmp_path):
    pilot = Pilot(tmp_path)
    pilot.save({"status": "processing", "video_id": "v1"})
    with (
        client(
            lambda r: httpx.Response(
                200,
                json={
                    "data": {
                        "status": "failed",
                        "failure_message": "secret raw error",
                    }
                },
            )
        ) as api,
        httpx.Client() as media,
        pytest.raises(PilotError),
    ):
        pilot.poll(api, media)
    assert pilot.status()["status"] == "failed"
    assert "secret raw error" not in json.dumps(pilot.read())


def test_os_lock_prevents_parallel_generation(tmp_path):
    with job_lock(tmp_path), pytest.raises(PilotError, match="실행 중"), job_lock(tmp_path):
        pass
    with job_lock(tmp_path):
        pass


def test_credentials_accept_bom_and_environment_override(tmp_path, monkeypatch):
    path = tmp_path / "heygen.env"
    path.write_text('HEYGEN_API_KEY="file-key"\nHEYGEN_AVATAR_ID=a1\n', encoding="utf-8-sig")
    monkeypatch.setenv("HEYGEN_API_KEY", "environment-key")
    assert load_credentials(path)["HEYGEN_API_KEY"] == "environment-key"
    monkeypatch.delenv("HEYGEN_API_KEY")
    assert load_credentials(path)["HEYGEN_API_KEY"] == "file-key"


@pytest.fixture
def playback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        lecture_preview,
        "settings",
        lambda: SimpleNamespace(
            deployment="local",
            runtime_root=tmp_path,
        ),
    )
    pilot = Pilot(tmp_path / "data" / "heygen-pilot")
    pilot.save({"status": "completed", "video_id": "test-provider-id"})
    pilot.video.write_bytes(MP4)
    session = SimpleNamespace(
        get=lambda *args: SimpleNamespace(id="section1", course_id="course1"),
        scalar=lambda *args: SimpleNamespace(status="active"),
    )
    app = create_app()
    app.dependency_overrides[db] = lambda: session
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="student1", role="student")
    with TestClient(app) as browser:
        yield browser, app, session, pilot


def test_playback_requires_enrollment_and_supports_range(playback):
    browser, app, session, _pilot = playback
    base = "/api/v1/sections/section1/lecture-preview"
    state = browser.get(base)
    assert state.status_code == 200
    assert state.json()["source_type"] == "manually_written_demo"
    assert "test-provider-id" not in state.text
    media = browser.get(state.json()["video_url"], headers={"Range": "bytes=0-11"})
    assert media.status_code == 206
    assert media.content == MP4[:12]
    assert media.headers["content-type"] == "video/mp4"
    assert media.headers["cache-control"] == "no-store"
    session.scalar = lambda *args: None
    assert browser.get(base).status_code == 404
    assert browser.get(base + "/file").status_code == 404
    app.dependency_overrides.pop(current_user)
    assert browser.get(base).status_code == 401
    assert browser.get(base + "/file").status_code == 401


def test_cloud_disables_local_sample(playback, monkeypatch):
    browser, _, _, _ = playback
    monkeypatch.setattr(lecture_preview, "settings", lambda: SimpleNamespace(deployment="cloud"))
    assert browser.get("/api/v1/sections/section1/lecture-preview").json() == {"enabled": False}
    assert browser.get("/api/v1/sections/section1/lecture-preview/file").status_code == 404


def test_missing_media_is_not_completed(playback):
    browser, _, _, pilot = playback
    pilot.video.unlink()
    state = browser.get("/api/v1/sections/section1/lecture-preview").json()
    assert state["status"] == "storage_missing"
    assert state["video_url"] is None
    assert browser.get("/api/v1/sections/section1/lecture-preview/file").status_code == 404
