import hashlib

import pytest
from pptx import Presentation
from sqlalchemy import select

from lerny import worker
from lerny.auth import COOKIE
from lerny.models import Chunk, Job, Material, MaterialVersion
from lerny.ppt_review import SlideReview, reviewed_text
from lerny.rag_index import indexed_ids
from test_gemini_integration import configured, fake_provider, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401


def test_reviewed_picture_and_merged_table_require_the_original_artifacts(tmp_path):
    import io
    from PIL import Image
    from lerny.ppt_review import native_value
    path = tmp_path / "table.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    grid = slide.shapes.add_table(2, 2, 0, 0, 2000000, 1000000)
    grid.table.cell(0, 0).merge(grid.table.cell(1, 0))
    grid.table.cell(0, 0).text = "same"
    grid.table.cell(0, 1).text = "0"
    grid.table.cell(1, 1).text = "1"
    png = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(png, format="PNG")
    picture = slide.shapes.add_picture(png, 0, 1500000)
    deck.save(path)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    tab = "same | 0\nsame | 1"
    assert native_value(grid) == tab
    literal = "visually reviewed label"
    review = SlideReview.model_validate({"source_sha256": digest(path.read_bytes()), "pages": [{
        "page": 1, "render_sha256": "1" * 64, "shapes": [
            {"shape_id": grid.shape_id, "text_sha256": digest(tab.encode())},
            {"shape_id": picture.shape_id, "text_sha256": digest(literal.encode()),
             "picture_sha256": digest(png.getvalue()), "transcription": literal},
        ]}]})
    assert reviewed_text(path, review)[1] == {grid.shape_id: tab, picture.shape_id: literal}
    review.pages[0].shapes[1].picture_sha256 = "2" * 64
    with pytest.raises(ValueError, match="INVALID_REVIEW_PICTURE"):
        reviewed_text(path, review)


def test_upload_does_not_overrule_conflicting_code_or_picture_readback(tmp_path):
    import io
    from PIL import Image
    from lerny.ppt_source_index import supplement, POLICY
    path = tmp_path / "conflicts.pptx"
    png = tmp_path / "page.png"
    Image.new("RGB", (500, 350), "white").save(png)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, deck.slide_width, deck.slide_height // 2)
    box.text = "x[0] = 'a  b'"
    picture = slide.shapes.add_picture(io.BytesIO(png.read_bytes()), 0, deck.slide_height // 2,
                                       deck.slide_width, deck.slide_height // 2)
    deck.save(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    unit = {"image": str(png), "source_kind": "ppt", "source_id": sha, "location": {"page": 1},
            "render_health": {"status": "checked"}, "pdf_inventory": {"words": [
                {"text": box.text, "valid_box": True, "bbox": [0, 0, 400, 200]}]}}
    class Reader:
        def call(self, stage, images, prompt, schema):
            if stage == POLICY:
                return {"regions": [{"id": str(box.shape_id), "text": "x[o] = 'a b'", "clear": True, "complete": True},
                                    {"id": str(picture.shape_id), "text": "12", "clear": True, "complete": True}]}
            assert stage == POLICY + "-picture"
            return {"text": "21", "readable": True, "uncertainties": [], "source_conflicts": []}
    result = {"chunks": [], "held": [], "evidence": {"source_sha256": sha}}
    supplement(path, {"source_plan": {"units": [unit]}}, result, tmp_path / "regions", Reader(), lambda: None)
    assert result["chunks"] == []
    assert result["evidence"]["ppt_page_review"]["missing_pages"] == [1]
    assert result["held"][0]["location"] == {"page": 1}


def deck(path, *, hide=False):
    ppt = Presentation()
    slide = ppt.slides.add_slide(ppt.slide_layouts[6])
    if hide:
        slide._element.set("show", "0")
    value = "x[0] = 0\nitem:   ABC\nfee: 15.0%"
    box = slide.shapes.add_textbox(0, 0, ppt.slide_width, ppt.slide_height)
    box.text = value
    slide.shapes.add_textbox(0, 0, ppt.slide_width, ppt.slide_height).text = "unreviewed"
    ppt.save(path)
    return {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pages": [{
        "page": 1, "render_sha256": "b" * 64,
        "shapes": [{"shape_id": box.shape_id, "text_sha256": hashlib.sha256(value.encode()).hexdigest()}],
    }]}, value


@pytest.mark.parametrize("fault", ["source", "text", "page", "duplicate", "hidden"])
def test_fails_closed_on_stale_or_ambiguous_review(tmp_path, fault):
    path = tmp_path / "source.pptx"
    review, _ = deck(path, hide=fault == "hidden")
    page = review["pages"][0]
    if fault == "source":
        review["source_sha256"] = "0" * 64
    if fault == "text":
        page["shapes"][0]["text_sha256"] = "0" * 64
    if fault == "page":
        page["page"] = 2
    if fault == "duplicate":
        page["shapes"] *= 2
    with pytest.raises(ValueError):
        reviewed_text(path, SlideReview.model_validate(review))


def test_review_appends_only_verified_active_public_text(integration, configured, fake_provider, monkeypatch):
    client, session, tokens = integration
    monkeypatch.setattr(worker, "heartbeat", lambda *_: None)
    path = configured.runtime_root / "data/files/source.pptx"
    path.parent.mkdir(parents=True, exist_ok=True)
    review, value = deck(path)
    version = session.get(MaterialVersion, "version")
    version.filename, version.object_key, version.sha256 = path.name, path.name, review["source_sha256"]
    version.extracted_text = "prior"
    version.extraction_report = {"review_queue": [{"id": "old"}], "held_count": 1}
    session.commit()
    url = "/api/v1/courses/course/rag/versions/version/reviewed-slides"

    def enqueue(key):
        return client.post(url, json=review, headers={"Idempotency-Key": key})

    response = enqueue("first")
    assert response.status_code == 202, response.text
    first = response.json()["job_id"]
    assert enqueue("first").json()["job_id"] == first
    assert worker.run_once(first)
    session.expire_all()
    assert session.get(Job, first).status == "succeeded", session.get(Job, first).error_code
    new = session.scalars(select(Chunk).where(Chunk.content == value)).one()
    assert new.locator["slide"] == 1 and indexed_ids([new], validate_vectors=True) == {new.id}
    assert session.get(Chunk, "src_stack_01").content == "Synthetic public stack rule 1"
    assert version.status == "ready" and version.extracted_text == "prior\n\n" + value
    assert version.extraction_report["review_queue"] == [{"id": "old"}]
    assert version.extraction_report["source_reviews"][0]["chunk_ids"] == [new.id]
    second = enqueue("again").json()["job_id"]
    assert worker.run_once(second)
    session.expire_all()
    assert session.get(Job, second).result["added_chunks"] == 0
    assert len(fake_provider) == 1 and fake_provider[0][0].endswith(":embedContent")
    assert not list(session.scalars(select(Job).where(Job.kind != "rag_reindex")))
    third = enqueue("before-revocation").json()["job_id"]
    session.get(Material, version.material_id).visibility = "private"
    session.commit()
    assert worker.run_once(third)
    session.expire_all()
    assert session.get(Job, third).error_code == "SOURCE_CHANGED"
    assert version.status == "ready" and len(fake_provider) == 1
    assert enqueue("private").status_code == 409
    client.cookies.set(COOKIE, tokens["student"][0])
    client.headers["X-CSRF-Token"] = tokens["student"][1]
    assert enqueue("forbidden").status_code in {403, 404}
