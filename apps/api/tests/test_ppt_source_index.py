import hashlib
import json

import pytest
from PIL import Image
from pptx import Presentation

from lerny.ppt_source_index import POLICY, PROMPT, READINGS, supplement
from video_extraction.shared.common import digest_file, signature
from video_extraction.shared.gemini import Gemini, SYSTEM


def slide_case(tmp_path, original, observed, *, kind="text", complete=True, clear=True,
               held=None, use_cache=False, merge_first_column=False):
    path = tmp_path / "demo.pptx"
    page = tmp_path / "page.png"
    Image.new("RGB", (320, 240), "white").save(page)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    if kind == "table":
        rows = [line.split(" | ") for line in original.split("\n")]
        shape = slide.shapes.add_table(len(rows), len(rows[0]), 0, 0, deck.slide_width, deck.slide_height)
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                shape.table.cell(row_index, column).text = value
        if merge_first_column:
            shape.table.cell(0, 0).merge(shape.table.cell(1, 0))
    else:
        shape = slide.shapes.add_textbox(0, 0, deck.slide_width, deck.slide_height)
        shape.text = original
    deck.save(path)
    sha = digest_file(path)
    shape_id = str(shape.shape_id)
    unit = {"image": str(page), "source_kind": "ppt", "source_id": sha, "location": {"page": 1},
            "render_health": {"status": "checked"},
            "pdf_inventory": {"words": [{"text": original, "valid_box": True, "bbox": [0, 0, 800, 400]}]}}
    holds = [{"location": {"page": 1}, "reasons": ["page_link_review_pending"],
              "bbox": [250, 250, 750, 750]}] if held == "link" else []
    summary = {"held_pages": [{"page": 1}]} if held == "page" else {}
    result = {"chunks": [], "held": holds, "evidence": {"source_sha256": sha, "summary": summary}}
    regions = [] if observed is None else [
        {"id": shape_id, "text": observed, "complete": complete, "clear": clear}
    ]

    class Reader:
        def call(self, stage, images, prompt, schema):
            assert not held and stage == POLICY
            return {"regions": regions}

    reader = Reader()
    if use_cache:
        cache = tmp_path / "cache"
        cache.mkdir()
        # The single target covers the full page. Recreate the input of the deployed v1 cache.
        crop = tmp_path / "cached-crop.png"
        with Image.open(page) as image:
            image.crop((0, 0, *image.size)).save(crop)
        model = "synthetic-model"
        sig = signature({"version": 2, "model": model, "system": SYSTEM,
                         "stage": "ppt-rendered-region-readback-v1", "images": [digest_file(page), digest_file(crop)],
                         "prompt": PROMPT + json.dumps([{"id": shape_id, "kind": kind}]), "schema": READINGS})
        (cache / (sig + ".json")).write_text(
            json.dumps({"signature": sig, "parsed": {"regions": regions}}), encoding="utf-8"
        )

        def forbidden(*args, **kwargs):
            pytest.fail("cache miss reached transport")

        reader = Gemini(cache, model, None, max_calls=0, transport=forbidden)
    supplement(path, {"source_plan": {"units": [unit]}}, result, tmp_path / "regions", reader, lambda: None)
    if use_cache:
        assert reader.stats["requests"] == 0 and reader.stats["cache_hits"] == 1
    return result


@pytest.mark.parametrize("observed", ["if seed:\n  print('n')", "if\tseed: print( 'n' )"])
def test_original_code_and_digest_when_only_layout_differs(tmp_path, observed):
    original = "if seed:\n    print('n')"
    result = slide_case(tmp_path, original, observed, use_cache=True)
    chunk, = result["chunks"]
    assert chunk["text"] == original
    assert chunk["source_region"]["text_sha256"] == hashlib.sha256(original.encode()).hexdigest()


@pytest.mark.parametrize("kind,original,observed", [
    ("text", "gain = 2 + 1", "gain = 2 - 1"),
    ("text", "print('a')", "print(‘a’)"),
    ("table", "total | 73", "total | 37"),
    ("text", "Output: 130", "Output: 131"),
    ("text", "ab = ba", "ba = ab"),
])
def test_visible_character_change_is_unresolved(tmp_path, kind, original, observed):
    result = slide_case(tmp_path, original, observed, kind=kind)
    assert not result["chunks"]
    assert [r["reason"] for r in result["evidence"]["ppt_page_review"]["unresolved"]] == ["independent_readback_mismatch"]


@pytest.mark.parametrize("complete,clear", [(False, True), (True, False), (False, False)])
def test_negative_flags_override_matching_pdf_words_and_text(tmp_path, complete, clear):
    result = slide_case(tmp_path, "x = 2", "x = 2", complete=complete, clear=clear)
    assert not result["chunks"] and len(result["evidence"]["ppt_page_review"]["unresolved"]) == 1


@pytest.mark.parametrize("held", ["link", "page"])
def test_hold_excludes_region_before_readback(tmp_path, held):
    result = slide_case(tmp_path, "x = 2", "x=2", held=held)
    assert result["chunks"] == [] and result["evidence"]["ppt_page_review"]["accepted"] == []


@pytest.mark.parametrize("observed", [None, "", " \t\n"], ids=["no-regions", "empty-text", "whitespace"])
def test_empty_readback_is_unresolved(tmp_path, observed):
    result = slide_case(tmp_path, "count = 12", observed)
    assert not result["chunks"]
    assert [r["reason"] for r in result["evidence"]["ppt_page_review"]["unresolved"]] == [
        "independent_readback_mismatch"
    ]


@pytest.mark.parametrize("original,observed", [
    pytest.param("A | 12 | ", "A |  | 12", id="same-row"),
    pytest.param("A | 7\n | B", "A | \n7 | B", id="across-rows"),
])
def test_shifted_table_cell_is_unresolved(tmp_path, original, observed):
    result = slide_case(tmp_path, original, observed, kind="table")
    assert not result["chunks"]
    assert [r["reason"] for r in result["evidence"]["ppt_page_review"]["unresolved"]] == [
        "independent_readback_mismatch"
    ]


def test_table_cell_spacing_keeps_native_text(tmp_path):
    original = "unit cost | 3 700\nnew total | 4 800"
    result = slide_case(tmp_path, original, "unitcost | 3700\nnew  total | 4800", kind="table")
    chunk, = result["chunks"]
    assert chunk["text"] == original


@pytest.mark.parametrize("observed", ["A | 7 | B", "A | 7 | \nB"], ids=["row-count", "cell-count"])
def test_table_requires_the_same_dimensions(tmp_path, observed):
    result = slide_case(tmp_path, "A | 7\n | B", observed, kind="table")
    assert not result["chunks"]
    assert result["evidence"]["ppt_page_review"]["unresolved"][0]["reason"] == "independent_readback_mismatch"


def test_merged_table_cell_matches_its_repeated_native_value(tmp_path):
    expected = "group | 2\ngroup | 3"
    result = slide_case(tmp_path, "group | 2\n | 3", expected, kind="table", merge_first_column=True)
    chunk, = result["chunks"]
    assert chunk["text"] == expected
