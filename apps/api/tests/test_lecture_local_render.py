import copy
import json
from pathlib import Path

import pytest
from lerny.lecture_local_render import FPS, build_timeline, subtitles

BASE = Path(__file__).resolve().parents[3] / "docs/contracts"


@pytest.fixture
def inputs():
    return (
        json.loads((BASE / "lecture.example.json").read_text(encoding="utf-8")),
        json.loads((BASE / "generation-input.example.json").read_text(encoding="utf-8"))[
            "generation_input"
        ],
    )


def test_fake_timeline_is_contiguous_exact_length_and_does_not_approve(inputs):
    spec, context = inputs
    before = copy.deepcopy(spec)
    result = build_timeline(spec, context)
    assert result["duration_frames"] == 40 * FPS
    assert result["entries"][0]["start_frame"] == 0
    assert result["entries"][-1]["end_frame"] == result["duration_frames"]
    for current, following in zip(result["entries"], result["entries"][1:]):
        assert current["end_frame"] == following["start_frame"]
        assert current["end_frame"] - current["start_frame"] >= FPS
    assert not result["heygen_submitted"] and not result["publication_allowed"]
    assert result["validation"]["render_allowed"] is False
    assert result["gesture_rendering"] == "not_applied"
    assert result["instructor_width_pixels"] / 1800 == 0.3
    assert result["material_width_pixels"] / 1800 == 0.7
    assert spec == before


def test_pop_and_gesture_metadata_follow_utterance_boundaries(inputs):
    entries = build_timeline(*inputs)["entries"]
    assert [b["value"] for b in entries[4]["stack"]] == [10, 20, 30]
    assert entries[4]["gesture_cues"][0]["target_element_id"] == "block_30"
    assert [b["value"] for b in entries[5]["stack"]] == [10, 20]
    assert entries[5]["removed"] == [30]


def test_end_event_does_not_change_current_utterance(inputs):
    spec, context = inputs
    spec["scenes"][1]["visual_events"][3]["trigger"]["boundary"] = "end"
    entry = build_timeline(spec, context)["entries"][5]
    assert [b["value"] for b in entry["stack"]] == [10, 20, 30]
    assert [b["value"] for b in entry["stack_after"]] == [10, 20]


def test_srt_uses_same_fake_timeline_and_preserves_text(inputs):
    timeline = build_timeline(*inputs)
    srt = subtitles(timeline)
    assert "00:00:00,000 -->" in srt and "00:00:40,000" in srt
    assert srt.count(" --> ") == 8
    assert all(e["text"] in srt for e in timeline["entries"])


@pytest.mark.parametrize("failure", ["invalid_pop", "held", "unknown_source"])
def test_invalid_or_held_spec_cannot_be_rendered(inputs, failure):
    spec, context = inputs
    if failure == "invalid_pop":
        spec["scenes"][1]["visual_events"][3]["expected_value"] = 99
    elif failure == "held":
        spec["generation_status"] = "insufficient_evidence"
    else:
        spec["scenes"][1]["utterances"][0]["source_refs"] = ["missing"]
    with pytest.raises(ValueError):
        build_timeline(spec, context)
