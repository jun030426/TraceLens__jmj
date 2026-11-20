"""Authorized, page-only handout viewing. Never returns original files or signed URLs."""
import hashlib
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Response
from sqlalchemy import select

from lerny.config import settings
from lerny.material_policy import student_source
from lerny.models import Course, Job, Material, MaterialVersion
from lerny.security import Actor, Db, course_access, deny

router = APIRouter(prefix="/api/v1")
FORMATS = {".pdf", ".pptx", ".docx", ".txt", ".md"}
RENDERER = "handout-v1"
MAX_PAGES = 250
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def handout_version(session, material):
    # Separate from student_source: examples remain valid evidence for AI learning.
    if material.deleted or material.kind != "lecture" or not student_source(material):
        return None
    version = session.get(MaterialVersion, material.active_version_id) if material.active_version_id else None
    if (not version or version.material_id != material.id or version.status != "ready"
            or Path(version.filename).suffix.lower() not in FORMATS):
        return None
    return version


def student_view(material, version):
    return {"id": material.id, "course_id": material.course_id, "title": material.title,
            "kind": material.kind, "week": material.week, "visibility": material.visibility,
            "internal_use": "none", "revision": material.revision,
            "version": {"id": version.id, "filename": version.filename, "status": version.status,
                        "error_code": None}, "view_url": f"/materials/{material.id}/view"}


def preview_access(session, actor, material_id):
    material = session.get(Material, material_id)
    if not material or material.deleted:
        deny(404)
    course_access(session, actor, material.course_id)
    version = handout_version(session, material)
    if not version:
        deny(404, "열람할 수 있는 강의자료가 아닙니다.")
    return material, version


def preview_id(version):
    return str(uuid5(NAMESPACE_URL, f"lerny:{RENDERER}:{version.id}:{version.sha256}"))


def ensure_preview(session, material, version):
    # Serialize first opens by version; one durable conversion for all enrolled students.
    session.scalar(select(MaterialVersion).where(MaterialVersion.id == version.id).with_for_update())
    job = session.get(Job, preview_id(version))
    if job is None:
        course = session.get(Course, material.course_id)
        job = Job(id=preview_id(version), owner_id=course.lead_teacher_id, course_id=material.course_id,
                  kind="material_preview", payload={"version_id": version.id, "sha256": version.sha256,
                                                     "_ai_provider": settings().ai_provider})
        session.add(job)
        session.commit()
    return job


@router.get("/materials/{material_id}/preview")
def preview(material_id: str, session: Db, actor: Actor, response: Response):
    material, version = preview_access(session, actor, material_id)
    job = ensure_preview(session, material, version)
    response.headers.update(PRIVATE_HEADERS)
    result = {"material_id": material.id, "course_id": material.course_id, "title": material.title,
              "version_id": version.id, "status": "preparing", "pages": []}
    if job.status == "succeeded" and (job.result or {}).get("sha256") == version.sha256:
        result["status"] = "ready"
        result["pages"] = [{"number": n, "width": page.get("width"), "height": page.get("height"),
                            "text": page.get("text", ""),
                            "image_url": f"/api/v1/materials/{material.id}/preview/{version.id}/pages/{n}"
                            if page.get("key") else None}
                           for n, page in enumerate(job.result["pages"], 1)]
    elif job.status in {"failed", "cancelled"}:
        result.update(status="failed", message="강의자료 화면을 준비하지 못했어요. 교수님께 문의해 주세요.")
    return result


@router.get("/materials/{material_id}/preview/{version_id}/pages/{page_number}")
def page_image(material_id: str, version_id: str, page_number: int, session: Db, actor: Actor):
    _, version = preview_access(session, actor, material_id)
    if version.id != version_id:
        deny(404)
    job = session.get(Job, preview_id(version))
    pages = (job.result or {}).get("pages", []) if job and job.status == "succeeded" else []
    if not 1 <= page_number <= len(pages):
        deny(404)
    page = pages[page_number - 1]
    key = page.get("key", "")
    if not re.fullmatch(r"handout-previews/[0-9a-f-]{36}/[0-9a-f]{64}\.webp", key):
        deny(404)
    if settings().uses_supabase_storage:
        from lerny.storage import download
        content = download(key, 8 * 1024 * 1024)
    else:
        path = settings().runtime_root / "data/previews" / key
        if not path.is_file():
            deny(404)
        content = path.read_bytes()
    return Response(content, media_type="image/webp", headers=PRIVATE_HEADERS)


def render_pages(source, filename, folder):
    """Bounded native conversion without AI, notes, attachments or executable HTML."""
    from video_extraction.pipeline.adapters import command, font_environment
    from PIL import Image
    import shutil

    suffix = Path(filename).suffix.lower()
    if suffix not in FORMATS or source.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("PREVIEW_FORMAT_OR_SIZE")
    if suffix in {".txt", ".md", ".docx"}:
        if suffix == ".docx":
            from docx import Document
            doc = Document(source)
            text = "\n".join([p.text for p in doc.paragraphs] +
                             [" | ".join(c.text for c in row.cells) for t in doc.tables for row in t.rows])
        else:
            text = source.read_text(encoding="utf-8-sig")
        if len(text) > MAX_PAGES * 5000:
            raise ValueError("PREVIEW_PAGE_LIMIT")
        return [{"text": text[i:i + 5000]} for i in range(0, max(1, len(text)), 5000)]
    pdf = source
    env = font_environment(folder)
    if suffix == ".pptx":
        deck = folder / "handout.pptx"
        shutil.copyfile(source, deck)
        command("soffice", [f"-env:UserInstallation={(folder / 'office-profile').as_uri()}",
                            "--headless", "--convert-to", "pdf", "--outdir", folder, deck], env)
        pdf = folder / "handout.pdf"
        if not pdf.is_file():
            raise ValueError("PREVIEW_CONVERSION_FAILED")
    info = command("pdfinfo", [pdf])
    count = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if not count or not 1 <= int(count[1]) <= MAX_PAGES:
        raise ValueError("PREVIEW_PAGE_LIMIT")
    pages = []
    for n in range(1, int(count[1]) + 1):
        stem = folder / f"page-{n}"
        command("pdftoppm", ["-f", n, "-l", n, "-scale-to", 1800, "-png", "-singlefile", pdf, stem], env)
        image_path = stem.with_suffix(".png")
        target = stem.with_suffix(".webp")
        with Image.open(image_path) as image:
            image.convert("RGB").save(target, "WEBP", quality=88)
            size = image.size
        text = command("pdftotext", ["-f", n, "-l", n, "-layout", pdf, "-"]).strip()[:12000]
        pages.append({"path": target, "width": size[0], "height": size[1], "text": text})
        image_path.unlink()
    return pages


def prepare_job(session, job):
    from lerny.storage import source_file
    version = session.get(MaterialVersion, job.payload["version_id"])
    material = session.get(Material, version.material_id) if version else None
    if (not material or handout_version(session, material) != version
            or version.sha256 != job.payload["sha256"]):
        raise ValueError("PREVIEW_SOURCE_CHANGED")
    with source_file(version) as source, TemporaryDirectory(prefix="lerny-handout-") as directory:
        if hashlib.sha256(source.read_bytes()).hexdigest() != version.sha256:
            raise ValueError("PREVIEW_SOURCE_CHANGED")
        pages = render_pages(source, version.filename, Path(directory))
        manifest = []
        for page in pages:
            page = dict(page)
            path = page.pop("path", None)
            if path:
                content = path.read_bytes()
                if len(content) > 8 * 1024 * 1024:
                    raise ValueError("PREVIEW_PAGE_TOO_LARGE")
                key = f"handout-previews/{job.id}/{hashlib.sha256(content).hexdigest()}.webp"
                if settings().uses_supabase_storage:
                    from lerny.storage import put, download, StorageUnavailable
                    try:
                        put(key, content)
                    except StorageUnavailable:
                        # A reclaimed lease can reuse already uploaded, identical pages.
                        if download(key, len(content)) != content:
                            raise
                else:
                    target = settings().runtime_root / "data/previews" / key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                page["key"] = key
            manifest.append(page)
    return {"sha256": version.sha256, "renderer": RENDERER, "pages": manifest}
