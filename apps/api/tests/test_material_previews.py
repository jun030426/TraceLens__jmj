"""Student original-file boundaries and native viewer; isolated DB, no paid APIs."""
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lerny import material_previews as previews, storage
from lerny.material_policy import student_source
from lerny.models import Enrollment, ExamPlan, Job, Material, MaterialVersion, Section
from lerny.security import COOKIE
from test_lecture_specs import api


def login(client, tokens, user):
    client.cookies.set(COOKIE, tokens[user][0])
    client.headers["X-CSRF-Token"] = tokens[user][1]


@pytest.fixture
def handout(api, monkeypatch, tmp_path):
    client, db, tokens = api
    material = db.get(Material, "material")
    material.kind = "lecture"
    db.add(Section(id="section", course_id="course", title="Class"))
    db.flush()
    db.add(Enrollment(id="enrollment", student_id="student", section_id="section", course_id="course", status="active"))
    db.commit()
    config = SimpleNamespace(uses_supabase_storage=False, runtime_root=tmp_path, ai_provider="gemini")
    monkeypatch.setattr(previews, "settings", lambda: config)
    login(client, tokens, "student")
    return client, db, tokens, config


@pytest.mark.parametrize("kind,filename,visible", [
    ("lecture", "lecture.pptx", True), ("lecture", "lecture.pdf", True),
    ("lecture", "lecture.docx", True), ("lecture", "lecture.md", True),
    ("lecture", "lecture.mp4", False), ("lecture", "code.py", False),
    ("example", "code.py", False), ("past_exam", "exam.pptx", False),
    ("assignment", "task.pdf", False), ("answer", "key.pdf", False),
    ("transcript", "text.txt", False),
])
def test_only_handouts_in_student_list(handout, kind, filename, visible):
    client, db, tokens, _ = handout
    material = db.get(Material, "material"); material.kind = kind
    db.get(MaterialVersion, "version").filename = filename
    db.commit()
    response = client.get("/api/v1/courses/course/materials")
    assert response.status_code == 200
    assert len(response.json()["items"]) == int(visible)
    if visible:
        assert response.json()["items"][0]["view_url"] == "/materials/material/view"
    else:
        assert client.get("/api/v1/materials/material/preview").status_code == 404
    login(client, tokens, "teacher")
    assert len(client.get("/api/v1/courses/course/materials").json()["items"]) == 1


@pytest.mark.parametrize("query", ["", "?version_id=version", "?version_id=old"])
def test_student_download_never_reads_or_signs_original(handout, monkeypatch, query):
    client, db, _, _ = handout
    def forbidden(*a, **k):
        pytest.fail("Original file storage must not be reached")
    monkeypatch.setattr(storage, "signed_download", forbidden)
    monkeypatch.setattr(storage, "download", forbidden)
    assert client.get("/api/v1/materials/material/file" + query).status_code == 403
    assert client.get("/api/v1/materials/material/transcript").status_code == 404
    assert client.get("/api/v1/materials/material/extraction-review").status_code == 404


def test_teacher_download_still_works(handout, monkeypatch):
    from lerny import materials
    client, _, tokens, config = handout
    path = config.runtime_root / "source.txt"; path.write_text("Original", encoding="utf-8")
    monkeypatch.setattr(materials, "settings", lambda: config)
    monkeypatch.setattr(materials, "source_path", lambda _: path)
    login(client, tokens, "teacher")
    response = client.get("/api/v1/materials/material/file")
    assert response.status_code == 200 and response.content == b"Original"
    assert "attachment" in response.headers["content-disposition"]


def test_preview_queues_once_without_changing_source_or_learning(handout):
    from lerny.gemini_runtime import needs_remote
    client, db, _, _ = handout
    before = db.get(MaterialVersion, "version").status
    for _ in range(2):
        response = client.get("/api/v1/materials/material/preview")
        assert response.status_code == 200 and response.json()["status"] == "preparing"
        assert "no-store" in response.headers["cache-control"]
        assert "object_key" not in response.text
    jobs = list(db.scalars(select(Job).where(Job.kind == "material_preview")))
    assert len(jobs) == 1 and not needs_remote(db, jobs[0])
    assert jobs[0].owner_id == "teacher"
    assert db.get(MaterialVersion, "version").status == before
    assert client.get(f"/api/v1/jobs/{jobs[0].id}").status_code == 404
    material = db.get(Material, "material"); material.kind = "example"
    assert student_source(material)  # AI evidence policy is intentionally unchanged.


def ready_preview(client, db, config):
    client.get("/api/v1/materials/material/preview")
    job = db.scalar(select(Job).where(Job.kind == "material_preview"))
    content = b"synthetic-image"
    key = f"handout-previews/{job.id}/{hashlib.sha256(content).hexdigest()}.webp"
    path = config.runtime_root / "data/previews" / key
    path.parent.mkdir(parents=True); path.write_bytes(content)
    job.status = "succeeded"
    job.result = {"sha256": "a" * 64, "pages": [{"key": key, "width": 1200, "height": 675, "text": "Slide text"}]}
    db.commit()
    result = client.get("/api/v1/materials/material/preview")
    assert result.json()["status"] == "ready"
    assert key not in result.text
    return result.json()["pages"][0]["image_url"]


@pytest.mark.parametrize("mutation", ["private", "deleted", "other_version", "example", "unenrolled", "internal"])
def test_revocation_checked_on_each_page_request(handout, mutation):
    client, db, _, config = handout
    url = ready_preview(client, db, config)
    assert client.get(url).status_code == 200
    m = db.get(Material, "material")
    if mutation == "private": m.visibility = "private"
    elif mutation == "deleted": m.deleted = True
    elif mutation == "other_version": m.active_version_id = None
    elif mutation == "example": m.kind = "example"
    elif mutation == "internal": m.internal_use = "validation_grading"
    else: db.get(Enrollment, "enrollment").status = "withdrawn"
    db.commit()
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/materials/material/preview").status_code == 404


def test_unauthorized_stale_and_out_of_range_pages(handout):
    client, db, tokens, config = handout
    url = ready_preview(client, db, config)
    assert client.get(url.replace("/version/", "/old/")).status_code == 404
    assert client.get(url[:-1] + "0").status_code == 404
    assert client.get(url[:-1] + "2").status_code == 404
    login(client, tokens, "outsider")
    assert client.get(url).status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_exam_resources_exclude_problem_and_answer_originals(handout):
    client, db, _, _ = handout
    db.add(ExamPlan(id="exam", course_id="course", title="Revision", start_week=1, end_week=2, published=True))
    for kind in ("example", "past_exam", "answer", "assignment"):
        db.add(Material(id=kind, course_id="course", title=kind, kind=kind, week=1, visibility="public"))
    db.commit()
    result = client.get("/api/v1/exam-plans/exam/practice").json()
    assert [r["id"] for r in result["resources"]] == ["material"]
    assert result["questions"] == []


def test_worker_preserves_original_and_reuses_text_preview(handout, monkeypatch, tmp_path):
    client, db, _, _ = handout
    original = tmp_path / "lecture.md"; original.write_text("<script>alert(1)</script>\n강의자료", encoding="utf-8")
    before = original.read_bytes()
    version = db.get(MaterialVersion, "version"); version.sha256 = hashlib.sha256(before).hexdigest()
    db.commit()
    client.get("/api/v1/materials/material/preview")
    job = db.scalar(select(Job).where(Job.kind == "material_preview"))
    @contextmanager
    def source(_): yield original
    monkeypatch.setattr(storage, "source_file", source)
    result = previews.prepare_job(db, job)
    assert result["pages"] == [{"text": original.read_text(encoding="utf-8")}]
    assert original.read_bytes() == before and version.status == "ready"
    job.result = result; job.status = "succeeded"; db.commit()
    assert client.get("/api/v1/materials/material/preview").json()["status"] == "ready"
    assert db.scalar(select(Job).where(Job.kind == "material_preview")).id == job.id


def test_pdf_page_renderer_bounds_and_conversion(tmp_path, monkeypatch):
    from PIL import Image
    from video_extraction.pipeline import adapters
    source = tmp_path / "source.pdf"; source.write_bytes(b"%PDF synthetic")
    calls = []
    def command(name, args, env=None):
        calls.append((name, args))
        if name == "pdfinfo": return "Pages: 2\n"
        if name == "pdftotext": return "Slide text"
        if name == "pdftoppm": Image.new("RGB", (800, 450), "white").save(str(args[-1]) + ".png")
        return ""
    monkeypatch.setattr(adapters, "command", command)
    pages = previews.render_pages(source, "slides.pdf", tmp_path)
    assert len(pages) == 2 and pages[0]["width"] == 800
    assert all(p["path"].suffix == ".webp" for p in pages)
    assert all(1800 in args for name, args in calls if name == "pdftoppm")
    monkeypatch.setattr(adapters, "command", lambda *a: "Pages: 9999\n")
    with pytest.raises(ValueError, match="PREVIEW_PAGE_LIMIT"):
        previews.render_pages(source, "slides.pdf", tmp_path)
