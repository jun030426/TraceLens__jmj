import hashlib
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Form, Header, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import Field
from sqlalchemy import select

from lerny.auth import Input
from lerny.config import settings
from lerny.courses import audit, view
from lerny.models import Concept, Course, Job, Material, MaterialVersion, Section, uid
from lerny.security import Actor, Db, course_access, deny, match_revision, staff_access

router = APIRouter(prefix="/api/v1")
KINDS = {"lecture", "example", "assignment", "transcript", "past_exam", "answer"}
SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md", ".c", ".java", ".py"}


def source_path(version):
    return settings().runtime_root / "data/files" / version.object_key


def material_access(session, actor, material_id, edit=False):
    material = session.get(Material, material_id)
    if not material or material.deleted:
        deny(404, "자료를 찾을 수 없습니다.")
    if edit:
        staff_access(session, actor, material.course_id)
    else:
        course_access(session, actor, material.course_id)
        if actor.role == "student" and material.visibility != "public":
            deny(404, "자료를 찾을 수 없습니다.")
    return material


def material_view(session, material):
    result = view(
        material, "id course_id title kind week visibility internal_use revision active_version_id"
    )
    version = session.scalar(
        select(MaterialVersion)
        .where(MaterialVersion.material_id == material.id)
        .order_by(MaterialVersion.version_no.desc())
        .limit(1)
    )
    result["version"] = (
        view(version, "id version_no filename status error_code concept_ids") if version else None
    )
    if version:
        processing = session.scalar(select(Job).where(
            Job.course_id == material.course_id, Job.kind.in_(["extract", "embed"]),
            Job.payload["version_id"].as_string() == version.id
        ).order_by(Job.created_at.desc()).limit(1))
        result["processing_job_id"] = processing.id if processing else None
        jobs = list(session.scalars(select(Job).where(Job.course_id == material.course_id, Job.kind.in_(["auto_concepts", "questions"]))))
        jobs = [j for j in jobs if j.payload.get("source_version_id") == version.id]
        result["learning_status"] = ("failed" if any(j.status == "failed" for j in jobs) else "waiting_ai" if any(j.status == "waiting_ai" for j in jobs) else "generating" if any(j.status in {"queued", "running"} for j in jobs) else "ready" if jobs else "not_started")
    return result


def save_version(file, material, actor, session):
    if settings().deployment == "cloud":
        deny(409, "클라우드 업로드 주소를 먼저 발급받아 주세요.")
    filename = (file.filename or "unknown").replace("\\", "/").split("/")[-1][:200]
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        deny(422, "현재 PDF·PPTX·DOCX·텍스트·예제 코드를 지원합니다. 다른 자료는 변환해 주세요.")
    root = settings().runtime_root / "data/files"
    root.mkdir(parents=True, exist_ok=True)
    key = uid() + suffix
    target = root / key
    limit = (
        (10 if suffix in {".txt", ".md"} else 1 if suffix in {".c", ".java", ".py"} else 100)
        * 1024
        * 1024
    )
    count, sha = 0, hashlib.sha256()
    try:
        with target.open("xb") as output:
            while data := file.file.read(1024 * 1024):
                count += len(data)
                if count > limit:
                    deny(413, "파일 크기 제한을 초과했습니다.")
                sha.update(data)
                output.write(data)
        if count == 0:
            deny(422, "빈 파일입니다.")
        if suffix == ".pdf":
            with target.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    deny(422, "PDF 형식을 확인해 주세요.")
        elif suffix in {".pptx", ".docx"}:
            with zipfile.ZipFile(target) as archive:
                entries = archive.infolist()
                expected = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
                if (
                    expected not in archive.namelist()
                    or len(entries) > 10000
                    or sum(e.file_size for e in entries) > 300 * 1024 * 1024
                ):
                    deny(422, "문서 구조 또는 압축 해제 크기 제한을 확인해 주세요.")
                if any("vbaproject" in e.filename.lower() for e in entries):
                    deny(422, "매크로가 포함된 문서는 지원하지 않습니다.")
        else:
            target.read_text(encoding="utf-8-sig")
        number = (
            session.scalar(
                select(MaterialVersion.version_no)
                .where(MaterialVersion.material_id == material.id)
                .order_by(MaterialVersion.version_no.desc())
                .limit(1)
            )
            or 0
        )
        version = MaterialVersion(
            material_id=material.id,
            version_no=number + 1,
            filename=filename,
            object_key=key,
            sha256=sha.hexdigest(),
        )
        session.add(version)
        session.flush()
        job = Job(
            owner_id=actor.id,
            course_id=material.course_id,
            kind="extract",
            payload={"version_id": version.id},
        )
        session.add(job)
        session.flush()
        return version, job
    except (zipfile.BadZipFile, UnicodeError):
        target.unlink(missing_ok=True)
        deny(422, "파일 형식이나 UTF-8 인코딩을 확인해 주세요.")
    except Exception:
        target.unlink(missing_ok=True)
        raise


@router.post("/courses/{course_id}/materials", status_code=201)
def upload(
    course_id: str,
    file: UploadFile,
    session: Db,
    actor: Actor,
    kind: str = Form(),
    week: int = Form(ge=1, le=52),
    visibility: str = Form(),
    internal_use: str = Form("none"),
):
    staff_access(session, actor, course_id)
    if (
        kind not in KINDS
        or visibility not in {"public", "private"}
        or internal_use not in {"none", "validation_grading"}
    ):
        deny(422, "자료 종류와 공개 범위를 확인해 주세요.")
    material = Material(
        course_id=course_id,
        title=(file.filename or "자료")[:200],
        kind=kind,
        week=week,
        visibility=visibility,
        internal_use=internal_use,
    )
    session.add(material)
    session.flush()
    version, job = save_version(file, material, actor, session)
    audit(session, actor, "material_uploaded", material.id)
    session.commit()
    return {
        "material_id": material.id,
        "version_id": version.id,
        "file_status": "available",
        "processing_job_id": job.id,
    }


@router.get("/courses/{course_id}/materials")
def list_materials(course_id: str, session: Db, actor: Actor):
    course_access(session, actor, course_id)
    query = select(Material).where(Material.course_id == course_id, Material.deleted.is_(False))
    if actor.role == "student":
        query = query.where(Material.visibility == "public")
    return {
        "items": [
            material_view(session, m)
            for m in session.scalars(query.order_by(Material.created_at.desc()))
        ]
    }


@router.get("/materials/{material_id}/file")
def file_download(material_id: str, session: Db, actor: Actor, version_id: str | None = None):
    material = material_access(session, actor, material_id)
    query = select(MaterialVersion).where(MaterialVersion.material_id == material_id)
    if version_id:
        query = query.where(MaterialVersion.id == version_id)
    version = session.scalar(query.order_by(MaterialVersion.version_no.desc()).limit(1))
    if not version:
        deny(404)
    if actor.role == "student" and version_id:
        latest = session.scalar(
            select(MaterialVersion.id)
            .where(MaterialVersion.material_id == material_id)
            .order_by(MaterialVersion.version_no.desc())
            .limit(1)
        )
        if version.id not in {latest, material.active_version_id}:
            deny(404, "교체된 자료는 더 이상 다운로드할 수 없습니다.")
    if settings().deployment == "cloud":
        from lerny.storage import signed_download
        return RedirectResponse(signed_download(version.object_key, version.filename), status_code=303)
    if not source_path(version).is_file():
        deny(404)
    return FileResponse(
        source_path(version),
        filename=version.filename,
        media_type="application/octet-stream",
        content_disposition_type="attachment",
    )


class AccessInput(Input):
    visibility: Literal["public", "private"]
    internal_use: Literal["none", "validation_grading"]


@router.patch("/materials/{material_id}/access")
def change_access(
    material_id: str,
    body: AccessInput,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    material_access(session, actor, material_id, edit=True)
    material = session.scalar(select(Material).where(Material.id == material_id).with_for_update())
    match_revision(material.revision, if_match)
    material.visibility, material.internal_use = body.visibility, body.internal_use
    material.revision += 1
    course = session.scalar(select(Course).where(Course.id == material.course_id).with_for_update())
    course.access_epoch += 1
    from lerny.automatic import enqueue_concepts, sync_progress
    if material.active_version_id:
        enqueue_concepts(session, material, session.get(MaterialVersion, material.active_version_id), actor.id)
    sync_progress(session, material.course_id)
    audit(session, actor, "material_access_changed", material_id, body.model_dump())
    session.commit()
    return material_view(session, material)


@router.post("/materials/{material_id}/versions", status_code=201)
def replace_material(
    material_id: str,
    file: UploadFile,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    material_access(session, actor, material_id, edit=True)
    material = session.scalar(select(Material).where(Material.id == material_id).with_for_update())
    match_revision(material.revision, if_match)
    version, job = save_version(file, material, actor, session)
    material.revision += 1
    session.commit()
    return {"version_id": version.id, "processing_job_id": job.id, "revision": material.revision}


@router.get("/materials/{material_id}/transcript")
def transcript(material_id: str, session: Db, actor: Actor):
    material = material_access(session, actor, material_id, edit=True)
    version = session.scalar(
        select(MaterialVersion)
        .where(MaterialVersion.material_id == material_id)
        .order_by(MaterialVersion.version_no.desc())
        .limit(1)
    )
    return {
        "text": version.extracted_text or "",
        "revision": material.revision,
        "version_id": version.id,
        "status": version.status,
    }


class TranscriptInput(Input):
    text: str = Field(min_length=1, max_length=1000000)


@router.put("/materials/{material_id}/transcript")
def edit_transcript(
    material_id: str,
    body: TranscriptInput,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    material_access(session, actor, material_id, edit=True)
    material = session.scalar(select(Material).where(Material.id == material_id).with_for_update())
    match_revision(material.revision, if_match)
    previous = session.scalar(
        select(MaterialVersion)
        .where(MaterialVersion.material_id == material_id)
        .order_by(MaterialVersion.version_no.desc())
        .limit(1)
    )
    version = MaterialVersion(
        material_id=material_id,
        version_no=previous.version_no + 1,
        filename=previous.filename,
        object_key=previous.object_key,
        sha256=previous.sha256,
        extracted_text=body.text,
        status="queued",
    )
    session.add(version)
    session.flush()
    job = Job(
        owner_id=actor.id,
        course_id=material.course_id,
        kind="extract",
        payload={"version_id": version.id, "manual_text": True},
    )
    session.add(job)
    material.revision += 1
    session.commit()
    return {"revision": material.revision, "job_id": job.id}


@router.delete("/materials/{material_id}", status_code=202)
def remove_material(
    material_id: str, session: Db, actor: Actor, if_match: str | None = Header(default=None)
):
    material_access(session, actor, material_id, edit=True)
    material = session.scalar(select(Material).where(Material.id == material_id).with_for_update())
    match_revision(material.revision, if_match)
    material.deleted = True
    material.revision += 1
    course = session.scalar(select(Course).where(Course.id == material.course_id).with_for_update())
    course.access_epoch += 1
    audit(session, actor, "material_deleted", material.id)
    session.commit()
    return {"status": "access_revoked", "physical_deletion": "pending"}


class ConceptInput(Input):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


@router.get("/courses/{course_id}/concepts")
def concepts(course_id: str, session: Db, actor: Actor):
    course_access(session, actor, course_id)
    return {
        "items": [
            view(c, "id name description revision")
            for c in session.scalars(
                select(Concept).where(Concept.course_id == course_id).order_by(Concept.created_at)
            )
        ]
    }


@router.post("/courses/{course_id}/concepts", status_code=201)
def create_concept(course_id: str, body: ConceptInput, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    concept = Concept(course_id=course_id, **body.model_dump())
    session.add(concept)
    session.commit()
    return view(concept, "id name description revision")


@router.patch("/concepts/{concept_id}")
def edit_concept(
    concept_id: str,
    body: ConceptInput,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    concept = session.scalar(select(Concept).where(Concept.id == concept_id).with_for_update())
    if not concept:
        deny(404)
    staff_access(session, actor, concept.course_id)
    match_revision(concept.revision, if_match)
    concept.name, concept.description = body.name, body.description
    concept.revision += 1
    session.commit()
    return view(concept, "id name description revision")


class ProgressInput(Input):
    mode: Literal["auto", "manual"] = "manual"
    concept_ids: list[str] = Field(max_length=300)


@router.put("/sections/{section_id}/progress")
def progress(
    section_id: str,
    body: ProgressInput,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    section = session.scalar(select(Section).where(Section.id == section_id).with_for_update())
    if not section:
        deny(404)
    staff_access(session, actor, section.course_id)
    match_revision(section.revision, if_match)
    ids = set(body.concept_ids)
    found = set(
        session.scalars(
            select(Concept.id).where(Concept.course_id == section.course_id, Concept.id.in_(ids))
        )
    )
    if found != ids:
        deny(422, "해당 과목의 개념만 진도에 지정할 수 있습니다.")
    section.progress_mode = body.mode
    section.progress_week = None
    section.progress, section.revision = sorted(ids), section.revision + 1
    if body.mode == "auto":
        from lerny.automatic import sync_progress
        sync_progress(session, section.course_id)
    session.commit()
    return {"concept_ids": section.progress, "revision": section.revision}


@router.post("/materials/{material_id}/learning", status_code=202)
def retry_learning(material_id: str, session: Db, actor: Actor):
    material = material_access(session, actor, material_id, edit=True)
    material = session.scalar(select(Material).where(Material.id == material.id).with_for_update())
    version = session.get(MaterialVersion, material.active_version_id) if material.active_version_id else None
    from lerny.automatic import eligible, enqueue_concepts
    if not version or not eligible(material, version):
        deny(409, "처리가 완료된 공개 강의 자료에서만 생성할 수 있어요.")
    jobs = [j for j in session.scalars(select(Job).where(Job.course_id == material.course_id, Job.kind.in_(["auto_concepts","questions"]))) if j.payload.get("source_version_id") == version.id]
    for job in jobs:
        if job.status == "failed":
            job.status, job.error_code, job.result = "queued", None, None
            job.payload = {**job.payload, "_ai_generation": job.payload.get("_ai_generation", 0) + 1}
    enqueue_concepts(session, material, version, actor.id)
    session.commit()
    return {"status": "queued"}


class WeekDate(Input):
    week: int = Field(ge=1, le=16)
    date: str

class WeeklyProgressInput(Input):
    mode: Literal["auto", "manual"]
    week: int = Field(ge=0, le=16)
    concept_ids: list[str] = Field(default_factory=list, max_length=300)
    schedule: list[WeekDate] | None = Field(default=None, min_length=16, max_length=16)

@router.get("/sections/{section_id}/weekly-progress")
def weekly_progress_view(section_id: str, session: Db, actor: Actor):
    section = session.get(Section, section_id)
    if not section: deny(404)
    staff_access(session, actor, section.course_id, "read")
    from lerny.automatic import sync_progress, weekly_content, section_schedule, calendar_week
    sync_progress(session, section.course_id)
    weeks = weekly_content(session, section.course_id)
    concepts = {c.id: c for c in session.scalars(select(Concept).where(Concept.course_id == section.course_id))}
    result = {"mode": section.progress_mode, "actual_week": section.progress_week, "calendar_week": calendar_week(session, section), "schedule": section_schedule(session, section), "revision": section.revision, "applied_ids": section.progress, "weeks": [{"week": week, "concepts": [{"id": cid, "name": concepts[cid].name, "description": concepts[cid].description} for cid in ids if cid in concepts]} for week, ids in sorted(weeks.items())]}
    session.commit()
    return result

@router.put("/sections/{section_id}/weekly-progress")
def save_weekly_progress(section_id: str, body: WeeklyProgressInput, session: Db, actor: Actor, if_match: str | None = Header(default=None)):
    from datetime import date
    from lerny.automatic import weekly_content, sync_progress, section_schedule
    section = session.scalar(select(Section).where(Section.id == section_id).with_for_update())
    if not section: deny(404)
    staff_access(session, actor, section.course_id)
    match_revision(section.revision, if_match)
    if body.schedule is not None:
        schedule = [r.model_dump() for r in body.schedule]
        try:
            for row in schedule: row["date"] = date.fromisoformat(row["date"]).isoformat()
        except ValueError: deny(422, "수업 날짜를 확인해 주세요.")
        if not schedule or [r["week"] for r in schedule] != list(range(1,len(schedule)+1)) or any(a["date"] > b["date"] for a,b in zip(schedule,schedule[1:])):
            deny(422, "주차는 1부터 순서대로, 날짜는 앞 주차보다 빠르지 않게 지정해 주세요.")
        section.week_schedule = schedule
    weeks = weekly_content(session, section.course_id)
    if body.mode == "manual" and body.schedule is None:
        if body.week > len(section_schedule(session, section)): deny(422, "수업 일정에 있는 주차를 선택해 주세요.")
        ids = set(body.concept_ids)
        if not ids <= set(weeks.get(body.week, [])): deny(422, "선택한 주차의 개념만 지정할 수 있어요.")
        section.progress = sorted({cid for week, concepts in weeks.items() if week < body.week for cid in concepts} | ids)
        section.progress_week = body.week
    elif body.mode == "auto": section.progress_week = None
    section.progress_mode = body.mode
    section.revision += 1
    sync_progress(session, section.course_id)
    session.commit()
    return {"revision": section.revision}
