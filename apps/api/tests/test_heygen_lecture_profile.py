import copy

import httpx
import pytest
from lerny.heygen_lecture_profile import (
    LERNY_LOOK_ID,
    LERNY_VOICE_ID,
    PromptTooLong,
    compile_script_request,
)
from lerny.heygen_video_agent import VideoAgentRun
from pydantic import ValidationError


def lesson():
    return {
        "title": "이진 트리",
        "narration": ["각 노드의 자식은 최대 두 개예요."],
        "key_facts": ["A의 왼쪽 자식은 B, 오른쪽 자식은 C."],
    }


def test_narration_compiles_to_the_actual_runner_without_network(tmp_path):
    data = lesson()
    original = copy.deepcopy(data)
    body = compile_script_request(data)
    calls = []

    def provider(request):
        import json

        calls.append(request)
        assert json.loads(request.content) == body
        return httpx.Response(200, json={"data": {"session_id": "session-test"}})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        run = VideoAgentRun(tmp_path)
        run.start(client, body, confirmed=True)
        run.start(client, body, confirmed=True)
    assert len(calls) == 1
    assert data == original
    assert body["avatar_id"] == LERNY_LOOK_ID
    assert body["voice_id"] == LERNY_VOICE_ID
    assert body["visibility"] == "private"
    assert body["prompt"].count(data["narration"][0]) == 1
    assert data["key_facts"][0] in body["prompt"]


@pytest.mark.parametrize(
    "extra",
    [
        {"avatar_id": "wrong"},
        {"voice_id": "wrong"},
        {"api_key": "secret"},
        {"language": "en-US"},
        {"narration": []},
        {"narration": ["   "]},
    ],
)
def test_lesson_cannot_override_resources_or_be_empty(extra):
    with pytest.raises(ValidationError):
        compile_script_request({**lesson(), **extra})


def test_long_lesson_is_rejected_without_silent_truncation():
    with pytest.raises(PromptTooLong):
        compile_script_request({**lesson(), "narration": ["가" * 3000] * 4})
