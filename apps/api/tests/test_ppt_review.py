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
