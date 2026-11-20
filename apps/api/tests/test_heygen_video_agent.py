import importlib.util
import json
import socket
from pathlib import Path

import httpx
import pytest
from lerny.heygen_pilot import PilotError, job_lock
from lerny.heygen_request_preview import PreviewOptions, compile_preview
from lerny.heygen_video_agent import AgentError, VideoAgentRun

BASE = Path(__file__).resolve().parents[3]
# Storage fixture only. This is not a rendered/playable lecture.
MP4 = b"\x00\x00\x00\x18ftypisom" + b"mock-container-storage-fixture"


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real network is forbidden in Video Agent tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


@pytest.fixture
def body():
    spec = json.loads((BASE / "docs/contracts/lecture.example.json").read_text(encoding="utf-8"))
    context = json.loads(
        (BASE / "docs/contracts/generation-input.example.json").read_text(encoding="utf-8")
    )["generation_input"]
    return compile_preview(
        spec, context, PreviewOptions(avatar_id="test-look", voice_id="test-voice")
    )["requests"][0]["body"]


def response(data):
    return httpx.Response(200, json={"data": data})


def api(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler), headers={"X-Api-Key": "secret-test"}
    )


def accept(request):
    return response({"session_id": "session-1", "video_id": None, "status": "thinking"})


def complete(request):
    if "/video-agents/" in request.url.path:
        return response({"session_id": "session-1", "status": "completed", "video_id": "video-1"})
    return response(
        {
            "id": "video-1",
            "status": "completed",
            "video_url": "https://files.heygen.ai/test.mp4?token=signed-secret",
        }
    )


def test_full_flow_restart_and_single_submission(tmp_path, body):
    calls, phase = [], iter(["thinking", "generating", "completed"])

    def provider(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path == "/v3/video-agents"
            assert VideoAgentRun(tmp_path).status()["status"] == "submitting"
            assert json.loads(request.content) == body
            return accept(request)
        if "/video-agents/" in request.url.path:
            status = next(phase)
            return response(
                {
                    "session_id": "session-1",
                    "status": status,
                    "video_id": None if status == "thinking" else "video-1",
                }
            )
        if len([p for _, p in calls if p == "/v3/videos/video-1"]) == 1:
            return response({"id": "video-1", "status": "processing"})
        return complete(request)

    def download(request):
        assert "x-api-key" not in request.headers
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert VideoAgentRun(tmp_path).status()["status"] == "storing"
        return httpx.Response(200, content=MP4)

    with (
        api(provider) as client,
        httpx.Client(
            transport=httpx.MockTransport(download),
            headers={"X-Api-Key": "should-not-leak"},
            auth=("user", "secret"),
            cookies={"secret": "cookie"},
        ) as media,
    ):
        run = VideoAgentRun(tmp_path)
        run.start(client, body, confirmed=True)
        assert run.poll(client, media)["status"] == "processing"
        run = VideoAgentRun(tmp_path)
        run.start(client, body, confirmed=True)
        assert run.poll(client, media)["status"] == "processing"
        assert run.poll(client, media)["status"] == "completed"
        assert run.poll(client, media)["status"] == "completed"
    assert sum(m == "POST" for m, _ in calls) == 1
    assert run.video.read_bytes() == MP4
    assert run.status()["bytes"] == len(MP4)
    assert len(run.status()["sha256"]) == 64
    assert not run.status()["publication_allowed"]
    saved = run.state_file.read_text()
    assert all(secret not in saved for secret in ("signed-secret", "secret-test", body["prompt"]))


def test_timeout_no_resubmission_and_explicit_recovery(tmp_path, body):
    calls = []

    def timeout(request):
        calls.append(request.method)
        raise httpx.ReadTimeout("provider may have accepted; secret", request=request)

    run = VideoAgentRun(tmp_path)
    with api(timeout) as client:
        for _ in range(2):
            with pytest.raises(AgentError, match="SUBMISSION_UNCERTAIN"):
                run.start(client, body, confirmed=True)
    assert calls == ["POST"]
    assert run.status()["status"] == "needs_attention"
    with pytest.raises(AgentError, match="INVALID_SESSION_ID"):
        run.attach_session("../bad")
    run.attach_session("session-1")
    with (
        api(complete) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=MP4))
        ) as media,
    ):
        assert VideoAgentRun(tmp_path).poll(client, media)["status"] == "completed"


@pytest.mark.parametrize(
    "mutation",
    [
        {"avatar_id": "<SELECTED_AVATAR_LOOK_ID>"},
        {"voice_id": ""},
        {"mode": "chat"},
        {"orientation": "portrait"},
        {"prompt": "x" * 10001},
        {"api_key": "secret"},
        {"style_id": "<UNSELECTED_STYLE>"},
    ],
)
def test_invalid_input_never_submits(tmp_path, body, mutation):
    with (
        api(lambda r: pytest.fail("POST forbidden")) as client,
        pytest.raises(AgentError, match="INVALID_AGENT_REQUEST"),
    ):
        VideoAgentRun(tmp_path).start(client, {**body, **mutation}, confirmed=True)
    assert not (tmp_path / "video-agent-job.json").exists()


def test_confirmation_and_changed_request(tmp_path, body):
    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        with pytest.raises(AgentError, match="CONFIRMATION_REQUIRED"):
            run.start(client, body)
        run.start(client, body, confirmed=True)
    with (
        api(lambda r: pytest.fail("POST forbidden")) as client,
        pytest.raises(AgentError, match="REQUEST_CHANGED"),
    ):
        run.start(client, {**body, "voice_id": "different"}, confirmed=True)


def test_studio_restart_polls_video_id_without_agent_session(tmp_path):
    from lerny.heygen_slides import compile_studio

    body = compile_studio("이진 트리", ["assetA", "assetB"], ["첫 번째 장", "두 번째 장"])
    for scene in body["scenes"]:
        avatar = scene["input"]
        assert avatar["engine"] == {"type": "avatar_v", "more_blinking": False}
        assert "motion_prompt" not in avatar and "expressiveness" not in avatar
    calls = []

    def provider(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            assert json.loads(req.content) == body
            return response({"video_id": "studio-1"})
        return response({
            "id": "studio-1", "status": "completed", "video_url": "https://files.heygen.ai/test.mp4"
        })

    with api(provider) as client, httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=MP4))
    ) as media:
        run = VideoAgentRun(tmp_path)
        run.start(client, body, confirmed=True)
        run = VideoAgentRun(tmp_path)
        run.start(client, body, confirmed=True)
        assert run.poll(client, media)["status"] == "completed"
    assert calls == [("POST", "/v3/videos"), ("GET", "/v3/videos/studio-1")]


def test_native_slide_notes_and_images_sync_in_visible_order(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_heygen_slides", BASE/"scripts/sync_heygen_slides.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    def page(num, hidden=False):
        props = {"notesProperties": {"speakerNotesObjectId": "speaker"}, "pageElements": [
            {"objectId": "speaker", "shape": {"text": {"textElements": [{"textRun": {"content": num}}]}}}
        ]}
        return {"objectId": num, "slideProperties": {"isSkipped": hidden, "notesPage": props}}

    deck = {"title": "Demo", "revisionId": "r1", "pageSize": {
        "width": {"unit": "EMU", "magnitude": 1600}, "height": {"unit": "EMU", "magnitude": 900}
    }, "slides": [page("second"), page("hidden", True), page("first")]}
    def google(req):
        assert req.headers["authorization"] == "Bearer google"
        if req.url.path.endswith("/thumbnail"):
            return httpx.Response(200, json={"contentUrl": "https://s.googleusercontent.com/" + req.url.path.split("/")[-2]})
        return httpx.Response(200, json=deck)
    def media(req):
        assert "authorization" not in req.headers and "x-api-key" not in req.headers
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + req.url.path.encode())
    uploaded = []
    def heygen(req):
        assert req.url.path == "/v3/assets" and "authorization" not in req.headers
        uploaded.append(req.content)
        return response({"asset_id": f"asset-{len(uploaded)}"})
    with (
        httpx.Client(transport=httpx.MockTransport(google), headers={"Authorization":"Bearer google"}) as g,
        httpx.Client(transport=httpx.MockTransport(media)) as m,
        api(heygen) as h,
    ):
        title, scripts, images = sync.read_slides(g, m, "deck")
        assert scripts == ["second", "first"]
        for _ in range(2):
            body = sync.sync_assets(h, tmp_path/"assets.json", title, scripts, images)
        assert len(uploaded) == 2
        assert [s["input"]["background"]["source"]["asset_id"] for s in body["scenes"]] == ["asset-1", "asset-2"]


def test_style_sent_once_and_style_change_cannot_reuse_submission(tmp_path, body):
    styled = {**body, "style_id": "verified-style"}
    sent = []

    def provider(request):
        sent.append(json.loads(request.content))
        return accept(request)

    run = VideoAgentRun(tmp_path)
    with api(provider) as client:
        with pytest.raises(AgentError, match="CONFIRMATION_REQUIRED"):
            run.start(client, styled)
        assert sent == []
        run.start(client, styled, confirmed=True)
        run.start(client, styled, confirmed=True)
        with pytest.raises(AgentError, match="REQUEST_CHANGED"):
            run.start(client, {**styled, "style_id": "different-style"}, confirmed=True)
    assert sent == [styled]


@pytest.mark.parametrize(
    "stage,status", [("session", "failed"), ("session", "cancelled"), ("video", "failed")]
)
def test_failure_is_terminal_without_download_or_retry(tmp_path, body, stage, status):
    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)

    def provider(request):
        if "/video-agents/" in request.url.path:
            return response(
                {
                    "session_id": "session-1",
                    "status": status if stage == "session" else "completed",
                    "video_id": "video-1",
                }
            )
        return response({"id": "video-1", "status": status, "failure_message": "secret"})

    with (
        api(provider) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: pytest.fail("download forbidden"))
        ) as media,
    ):
        assert run.poll(client, media)["status"] == status
    with api(lambda r: pytest.fail("network forbidden")) as client:
        assert run.start(client, body, confirmed=True)["status"] == status
        assert run.poll(client, client)["status"] == status


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retryable_get_keeps_ids_and_retry_after(tmp_path, body, code):
    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    with api(lambda r: httpx.Response(code, headers={"Retry-After": "90"})) as client:
        state = run.poll(client, client)
    assert state["session_id"] == "session-1"
    assert state["error_code"] == "STATUS_RETRYABLE"
    assert state["retry_after_seconds"] == 90


@pytest.mark.parametrize(
    "media_response,error",
    [
        (lambda: httpx.Response(200, content=b"html-error-page"), "NOT_MP4"),
        (
            lambda: httpx.Response(200, content=MP4, headers={"Content-Length": "999"}),
            "INCOMPLETE_MEDIA",
        ),
        (
            lambda: httpx.Response(
                200, content=MP4, headers={"Content-Length": str(101 * 1024 * 1024)}
            ),
            "INVALID_MEDIA_SIZE",
        ),
        (
            lambda: httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"}),
            "INVALID_MEDIA_URL",
        ),
        (lambda: httpx.Response(403), "MEDIA_SAVE_FAILED"),
    ],
)
def test_failed_download_resumes_without_generation(tmp_path, body, media_response, error):
    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    with (
        api(complete) as client,
        httpx.Client(transport=httpx.MockTransport(lambda r: media_response())) as media,
        pytest.raises(AgentError, match=error),
    ):
        run.poll(client, media)
    assert run.status()["status"] == "storing"
    assert not run.video.exists() and not (tmp_path / "video.mp4.part").exists()
    with (
        api(complete) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=MP4))
        ) as media,
    ):
        assert run.poll(client, media)["status"] == "completed"
        run.video.unlink()
        assert run.status()["status"] == "storage_missing"
        assert run.poll(client, media)["status"] == "completed"


def test_corrupt_state_and_lock_never_post(tmp_path, body):
    run = VideoAgentRun(tmp_path)
    run.state_file.write_text("broken", encoding="utf-8")
    with api(lambda r: pytest.fail("network forbidden")) as client:
        with pytest.raises(AgentError, match="STATE_UNREADABLE"):
            run.start(client, body, confirmed=True)
        with job_lock(tmp_path), pytest.raises(PilotError):
            run.start(client, body, confirmed=True)


def test_cli_defaults_to_offline_and_requires_flags(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "video_agent_cli", BASE / "scripts/heygen_video_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_credentials", lambda *a: pytest.fail("credentials forbidden"))
    assert module.main(["--run-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_started"
    for args in (["generate"], ["resume"], ["generate", "--allow-network"]):
        with pytest.raises(SystemExit) as exc:
            module.main([*args, "--run-dir", str(tmp_path)])
        assert exc.value.code == 2


@pytest.mark.parametrize(
    "payload", [{"data": {}}, {"data": {"session_id": "../unsafe"}}, {"data": None}]
)
def test_malformed_acceptance_never_reposts(tmp_path, body, payload):
    calls = []

    def provider(request):
        calls.append(request.method)
        return httpx.Response(200, json=payload)

    with api(provider) as client:
        for _ in range(2):
            with pytest.raises(AgentError, match="SUBMISSION_UNCERTAIN"):
                VideoAgentRun(tmp_path).start(client, body, confirmed=True)
    assert calls == ["POST"]


@pytest.mark.parametrize("status", ["awaiting_input", "completed"])
def test_session_without_usable_video_needs_attention(tmp_path, body, status):
    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    with api(lambda r: response({"session_id": "session-1", "status": status})) as client:
        assert run.poll(client, client)["status"] == "needs_attention"


def test_stream_failure_keeps_existing_file_and_cleans_partial(tmp_path, body):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield MP4[:20]
            raise httpx.ReadError("signed-url-secret")

    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    run.video.write_bytes(b"previous-file")
    with (
        api(complete) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=BrokenStream()))
        ) as media,
        pytest.raises(AgentError, match="MEDIA_SAVE_FAILED"),
    ):
        run.poll(client, media)
    assert run.video.read_bytes() == b"previous-file"
    assert not (tmp_path / "video.mp4.part").exists()
    assert run.status()["status"] == "storing"


def test_stream_limit_without_content_length(tmp_path, body, monkeypatch):
    import lerny.heygen_video_agent as runner

    monkeypatch.setattr(runner, "MAX_VIDEO_BYTES", 20)

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield MP4[:16]
            yield MP4[16:]

    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    with (
        api(complete) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))
        ) as media,
        pytest.raises(AgentError, match="MEDIA_TOO_LARGE"),
    ):
        run.poll(client, media)
    assert not run.video.exists()


def test_allowed_redirect_and_client_auth_is_not_forwarded(tmp_path, body):
    seen = []

    def download(request):
        seen.append(str(request.url))
        assert not any(k in request.headers for k in ("x-api-key", "authorization", "cookie"))
        if len(seen) == 1:
            return httpx.Response(
                302, headers={"Location": "https://resource2.heygen.ai/final.mp4"}
            )
        return httpx.Response(200, content=MP4)

    run = VideoAgentRun(tmp_path)
    with api(accept) as client:
        run.start(client, body, confirmed=True)
    with (
        api(complete) as client,
        httpx.Client(
            transport=httpx.MockTransport(download), headers={"Authorization": "secret"}
        ) as media,
    ):
        assert run.poll(client, media)["status"] == "completed"
    assert len(seen) == 2


def test_cli_generate_resume_with_only_mock_transports(tmp_path, body, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "video_agent_cli", BASE / "scripts/heygen_video_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_credentials", lambda *a: {"HEYGEN_API_KEY": "fake-key"})
    calls = []

    def provider(request):
        calls.append(request.method)
        return accept(request) if request.method == "POST" else complete(request)

    original_client = httpx.Client

    def mock_client(**kwargs):
        handler = provider if "headers" in kwargs else lambda r: httpx.Response(200, content=MP4)
        return original_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(module.httpx, "Client", mock_client)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert (
        module.main(
            [
                "generate",
                "--run-dir",
                str(tmp_path),
                "--request-body",
                str(path),
                "--allow-network",
                "--confirm-generate",
            ]
        )
        == 0
    )
    assert module.main(["resume", "--run-dir", str(tmp_path), "--allow-network"]) == 0
    assert calls == ["POST", "GET", "GET"]
    assert "fake-key" not in capsys.readouterr().out
