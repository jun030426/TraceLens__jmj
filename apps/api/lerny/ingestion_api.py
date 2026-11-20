"""Authenticated teacher upload/enqueue/status endpoints for the ingestion worker."""

import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select, text

from lerny import storage
from lerny.auth import Input
from lerny.config import settings
from lerny.courses import audit
from lerny.ingestion_store import MODEL, PIPELINE, SupabaseIngestion
from lerny.models import UploadIntent, now, uid
from lerny.security import Actor, Db, deny, staff_access

router = APIRouter(prefix="/api/v1")
SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md", ".py", ".java", ".c",
            ".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".flac",
            ".png", ".jpg", ".jpeg", ".webp"}


class UploadInput(Input):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0, le=1024 * 1024 * 1024)
    title: str = Field(min_length=1, max_length=200)
    week: int = Field(default=1, ge=1, le=52)
    source_key: str = Field(min_length=1, max_length=100)
    allow_ai_processing: Literal[True]


def visible_job(row):
    return {key: row[key] for key in ("id", "source_id", "status", "current_stage",
                                      "progress_percentage", "last_completed_stage", "attempt_count",
                                      "error_code", "result", "created_at", "updated_at")}


@router.post("/courses/{course_id}/ingestion/uploads", status_code=201)
def prepare(course_id: str, body: UploadInput, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    if not settings().uses_supabase_storage:
        deny(409, "Supabase 원본 저장소 설정이 필요합니다.")
    filename = body.filename.replace("\\", "/").split("/")[-1]
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        deny(422, "지원하지 않는 자료 형식입니다.")
    bucket = storage.request("GET", "/bucket/" + settings().storage_bucket).json()
    if bucket.get("public") is not False:
        deny(409, "비공개 원본 버킷이 필요합니다.")
    limit = min(1024 * 1024 * 1024, bucket.get("file_size_limit") or 50 * 1024 * 1024)
    if body.size > limit:
        deny(413, f"현재 원본 저장소는 파일당 {limit // (1024 * 1024)}MB까지 지원합니다.")
    intent = UploadIntent(owner_id=actor.id, course_id=course_id,
                          object_key="ingestion/staging/" + uid() + suffix,
                          filename=filename, size=body.size,
                          metadata_={**body.model_dump(), "workflow": PIPELINE},
                          expires_at=now() + timedelta(hours=2))
    session.add(intent)
    session.flush()
    url = storage.signed_upload(intent.object_key)
    session.commit()
    return {"upload_id": intent.id, "url": url, "method": "PUT"}


@router.post("/ingestion/uploads/{upload_id}/complete", status_code=201)
def complete(upload_id: str, session: Db, actor: Actor):
    intent = session.scalar(select(UploadIntent).where(UploadIntent.id == upload_id).with_for_update())
    if not intent or intent.owner_id != actor.id or intent.metadata_.get("workflow") != PIPELINE:
        deny(404)
    staff_access(session, actor, intent.course_id)
    if intent.result:
        return intent.result
    if intent.expires_at <= now():
        deny(410, "업로드 시간이 만료되었습니다.")
    # Copy to a non-uploadable immutable key before hashing; later staging changes cannot race it.
    raw_key = "ingestion/raw/" + intent.id + Path(intent.filename).suffix.lower()
    store = SupabaseIngestion()
    try:
        store.copy_original(intent.object_key, raw_key)
        with TemporaryDirectory(prefix="ingestion-upload-") as directory:
            path = Path(directory) / ("source" + Path(intent.filename).suffix.lower())
            digest = store.download(raw_key, path, intent.size)
            if path.stat().st_size != intent.size:
                deny(422, "업로드 파일 크기가 일치하지 않습니다.")
            if path.suffix in {".pdf", ".pptx", ".docx", ".txt", ".md", ".py", ".java", ".c"}:
                from lerny.cloud_uploads import validate_bytes
                if path.stat().st_size > 100 * 1024 * 1024:
                    deny(413, "문서는 100MB 이하로 등록해 주세요.")
                validate_bytes(path.read_bytes(), intent.filename)
    finally:
        store.close()
    source = session.execute(text("""
        INSERT INTO public.ingestion_sources(course_id,source_key,title,week_number,visibility,internal_use,created_by)
        VALUES(:course,:key,:title,:week,'public','none',:actor)
        ON CONFLICT(course_id,source_key) DO UPDATE SET title=excluded.title,week_number=excluded.week_number
        RETURNING id,visibility,internal_use
        """), {"course": intent.course_id, "key": intent.metadata_["source_key"],
               "title": intent.metadata_["title"], "week": intent.metadata_["week"], "actor": actor.id}).mappings().one()
    if source["visibility"] != "public" or source["internal_use"] != "none":
        deny(409, "비공개·내부 검증 자료는 이 생성 경로로 처리할 수 없습니다.")
    config = {"embedding_model": MODEL, "dimensions": 768, "answer_model": settings().gemini_answer_model,
              "chunk_limit": 1800, "allow_ai_processing": True}
    job = session.execute(text("""
        SELECT * FROM public.ingestion_enqueue(CAST(:source AS uuid),:filename,:path,:hash,:pipeline,CAST(:config AS jsonb))
        """), {"source": str(source["id"]), "filename": intent.filename, "path": raw_key,
               "hash": digest, "pipeline": PIPELINE, "config": json.dumps(config)}).mappings().one()
    intent.result = {"job_id": str(job["id"]), "source_id": str(source["id"]), "status": job["status"]}
    audit(session, actor, "ingestion_enqueued", str(job["id"]), {"pipeline": PIPELINE})
    session.commit()
    # Staging is disposable after the immutable source and queue transaction are durable.
    try:
        storage.delete_object(intent.object_key)
    except storage.StorageUnavailable:
        pass
    return intent.result


@router.get("/courses/{course_id}/ingestion/jobs")
def list_jobs(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    rows = session.execute(text("""SELECT j.* FROM public.ingestion_jobs j
        JOIN public.ingestion_sources s ON s.id=j.source_id WHERE s.course_id=:course
        ORDER BY j.created_at DESC LIMIT 100"""), {"course": course_id}).mappings()
    return {"items": [visible_job(row) for row in rows]}


@router.get("/ingestion/jobs/{job_id}")
def job_detail(job_id: UUID, session: Db, actor: Actor):
    row = session.execute(text("""SELECT j.*,s.course_id FROM public.ingestion_jobs j
        JOIN public.ingestion_sources s ON s.id=j.source_id WHERE j.id=:id"""), {"id": job_id}).mappings().first()
    if not row:
        deny(404)
    staff_access(session, actor, row["course_id"])
    result = visible_job(row)
    result["review_items"] = row["review_items"]
    for table in ("concept_quizzes", "shorts_scripts"):
        # Teacher-only review includes pending drafts; student publication is a separate policy.
        items = session.execute(text(f"SELECT * FROM public.{table} WHERE job_id=:id ORDER BY id"),
                                {"id": job_id}).mappings()
        result[table] = [{k: v for k, v in item.items() if k != "lease_token"} for item in items]
    return result
