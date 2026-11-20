"""Authorize a staging upload, validate its bytes, then publish an immutable source."""

import hashlib
import zipfile
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from lerny import storage
from lerny.auth import Input
from lerny.config import settings
from lerny.courses import audit
from lerny.materials import KINDS, SUFFIXES, material_access
from lerny.material_policy import internal_use_for, visibility_for
from lerny.models import Job, Material, MaterialVersion, UploadIntent, now, uid
from lerny.security import Actor, Db, deny, match_revision, staff_access

router = APIRouter(prefix="/api/v1")


class UploadInput(Input):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0, le=1024 * 1024 * 1024)
    kind: str | None = None
    week: int = Field(default=1, ge=1, le=52)
    visibility: str = "public"
    internal_use: str = "none"
    material_id: str | None = None
    revision: int | None = None


def validate_bytes(content, filename):
    suffix = Path(filename).suffix.lower()
    try:
        with TemporaryDirectory(prefix="lerny-validate-") as directory:
            path = Path(directory) / ("source" + suffix)
            path.write_bytes(content)
            if suffix == ".pdf":
                if not content.startswith(b"%PDF-"):
                    deny(422, "PDF 형식을 확인해 주세요.")
            elif suffix in {".pptx", ".docx"}:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    expected = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
                    if (
                        expected not in archive.namelist()
                        or len(entries) > 10000
                        or sum(e.file_size for e in entries) > 300 * 1024 * 1024
                        or any("vbaproject" in e.filename.lower() for e in entries)
                    ):
                        deny(422, "문서 구조·압축 크기·매크로 포함 여부를 확인해 주세요.")
            elif suffix == ".mp4":
                from lerny.media_validation import validate_mp4
                try:
                    validate_mp4(content)
                except ValueError:
                    deny(422, "MP4 영상 형식을 확인해 주세요.")
            else:
                content.decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeError):
        deny(422, "파일 형식이나 UTF-8 인코딩을 확인해 주세요.")


def file_limit(filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        deny(422, "지원하지 않는 자료 형식입니다.")
    from lerny import media_storage
    if suffix == ".mp4" and settings().uses_supabase_storage and media_storage.enabled():
        return settings().media_file_limit_mb * 1024 * 1024
    mb = 10 if suffix in {".txt", ".md"} else 1 if suffix in {".c", ".java", ".py"} else 100
    return min(mb, settings().cloud_file_limit_mb) * 1024 * 1024


@router.get("/uploads/config")
def upload_config(actor: Actor):
    return {
        "direct": settings().uses_supabase_storage,
        "max_file_bytes": settings().cloud_file_limit_mb * 1024 * 1024,
        "limits": {suffix: file_limit("source" + suffix) for suffix in sorted(SUFFIXES)},
    }


@router.post("/courses/{course_id}/uploads", status_code=201)
def prepare(course_id: str, body: UploadInput, session: Db, actor: Actor):
    if not settings().uses_supabase_storage:
        deny(409, "로컬에서는 기존 파일 업로드를 사용해 주세요.")
    staff_access(session, actor, course_id)
    if body.material_id:
        material = material_access(session, actor, body.material_id, edit=True)
        if material.course_id != course_id:
            deny(404)
        match_revision(material.revision, str(body.revision) if body.revision else None)
        # Replacing a file keeps the instructor's existing classification.
        body = body.model_copy(update={"kind": material.kind})
    if not body.kind:
        deny(422, "파일의 자료 종류를 직접 선택해 주세요.")
    if (
        body.kind not in KINDS
        or body.visibility not in {"public", "private"}
        or (body.internal_use not in {"none", "validation_grading"})
    ):
        deny(422, "자료 종류와 공개 범위를 확인해 주세요.")
    filename = body.filename.replace("\\", "/").split("/")[-1]
    if body.size > file_limit(filename):
        deny(413, "파일 크기 제한을 초과했습니다.")
    intent = UploadIntent(
        owner_id=actor.id,
        course_id=course_id,
        material_id=body.material_id,
        object_key="staging/" + uid() + Path(filename).suffix.lower(),
        filename=filename,
        size=body.size,
        metadata_={**body.model_dump(), "internal_use": internal_use_for(body.kind),
                   "visibility": visibility_for(body.kind, body.visibility)},
        expires_at=now() + timedelta(hours=2),
    )
    session.add(intent)
    session.flush()
    from lerny import media_storage
    if Path(filename).suffix.lower() == ".mp4" and media_storage.enabled():
        intent.object_key = "s3media/" + intent.id + ".mp4"
        value = media_call("begin", id=intent.id, size=intent.size)
        intent.metadata_ = {**intent.metadata_, "media_upload_id": value["upload_id"]}
        session.commit()
        return {"upload_id": intent.id, "url": "", "method": "MULTIPART"}
    url = storage.signed_upload(intent.object_key)
    session.commit()
    return {"upload_id": intent.id, "url": url, "method": "PUT"}


def media_call(action, **body):
    from lerny.media_storage import bridge
    try:
        return bridge(action, **body)
    except ValueError as exc:
        messages = {
            "INVALID_MP4": "MP4 영상 형식을 확인해 주세요.",
            "MEDIA_SIZE_MISMATCH": "전송한 영상 크기가 일치하지 않습니다. 다시 선택해 주세요.",
            "MEDIA_UPLOAD_INCOMPLETE": "영상 전송이 아직 끝나지 않았어요. 미완료 파일을 다시 올려 주세요.",
            "MEDIA_UPLOAD_EXPIRED": "영상 업로드 시간이 만료되었습니다. 다시 선택해 주세요.",
        }
        if str(exc) in messages:
            deny(422, messages[str(exc)])
        deny(503, "영상 저장소 연결을 확인하지 못했어요. 잠시 후 미완료 파일을 다시 올려 주세요.")


@router.post("/uploads/{upload_id}/parts")
def upload_parts(upload_id: str, session: Db, actor: Actor):
    intent = session.get(UploadIntent, upload_id)
    if not intent or intent.owner_id != actor.id or not intent.object_key.startswith("s3media/"):
        deny(404)
    staff_access(session, actor, intent.course_id)
    if intent.result:
        return {"complete": True, "parts": []}
    if intent.expires_at <= now():
        deny(410, "업로드 시간이 만료되었습니다. 다시 선택해 주세요.")
    return media_call("parts", id=intent.id, upload_id=intent.metadata_["media_upload_id"], size=intent.size)


@router.post("/uploads/{upload_id}/complete", status_code=201)
def complete(upload_id: str, session: Db, actor: Actor):
    if not settings().uses_supabase_storage:
        deny(409)
    intent = session.scalar(
        select(UploadIntent).where(UploadIntent.id == upload_id).with_for_update()
    )
    if not intent or intent.owner_id != actor.id:
        deny(404)
    if intent.metadata_.get("workflow") == "ingestion-worker-v1":
        deny(409, "Ingestion 업로드 완료 경로를 사용해 주세요.")
    staff_access(session, actor, intent.course_id)
    if intent.result:
        return intent.result
    if intent.expires_at <= now():
        deny(410, "업로드 시간이 만료되었습니다. 다시 선택해 주세요.")
    if intent.material_id:
        material_access(session, actor, intent.material_id, edit=True)
        material = session.scalar(
            select(Material).where(Material.id == intent.material_id).with_for_update()
        )
        match_revision(material.revision, str(intent.metadata_.get("revision")))
    else:
        material = Material(
            course_id=intent.course_id,
            title=intent.filename,
            **{k: intent.metadata_[k] for k in ("kind", "week")},
            visibility=visibility_for(intent.metadata_["kind"], intent.metadata_["visibility"]),
            internal_use=internal_use_for(intent.metadata_["kind"]),
        )
        session.add(material)
        session.flush()
    if intent.object_key.startswith("s3media/"):
        # Complete consumes the multipart token. The bridge validates and hashes
        # the immutable S3 object with bounded memory, without proxying GBs here.
        import re
        value = media_call("complete", id=intent.id, upload_id=intent.metadata_["media_upload_id"], size=intent.size)
        if value.get("size") != intent.size or not re.fullmatch(r"[a-f0-9]{64}", value.get("sha256", "")):
            deny(503, "영상 저장 결과를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")
        key, checksum = intent.object_key, value["sha256"]
    else:
        try:
            content = storage.download(intent.object_key, file_limit(intent.filename))
        except ValueError:
            deny(413, "파일 크기 제한을 초과했습니다.")
        if len(content) != intent.size:
            deny(422, "업로드한 파일 크기가 일치하지 않습니다.")
        validate_bytes(content, intent.filename)
        # A staging upload token can never change the published final object.
        key = uid() + Path(intent.filename).suffix.lower()
        storage.put(key, content)
        checksum = hashlib.sha256(content).hexdigest()
    previous = session.scalar(
        select(MaterialVersion.version_no)
        .where(MaterialVersion.material_id == material.id)
        .order_by(MaterialVersion.version_no.desc())
        .limit(1)
    )
    version = MaterialVersion(
        material_id=material.id,
        version_no=(previous or 0) + 1,
        filename=intent.filename,
        object_key=key,
        sha256=checksum,
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
    if intent.material_id:
        material.revision += 1
    audit(session, actor, "material_uploaded", material.id)
    session.flush()
    intent.result = {
        "material_id": material.id,
        "version_id": version.id,
        "processing_job_id": job.id,
        "revision": material.revision,
        "file_status": "available",
    }
    session.commit()
    return intent.result
