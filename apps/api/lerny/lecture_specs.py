"""Authenticated, manual lecture-spec intake. No Gemini/HeyGen requests or queue dispatch."""

import json
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import defer

from lerny.lecture_contract import Identifier, LectureSpec, StrictModel, Text, report, validate_spec
from lerny.lecture_presentation import presentation_profile
from lerny.models import Chunk, Concept, Job, Material, MaterialVersion, uid
from lerny.security import Actor, Db, deny, digest, staff_access

router = APIRouter(prefix="/api/v1", tags=["lecture-specs"])
MAX_BODY_BYTES = 262144


class CreateRequest(StrictModel):
    concept_id: Identifier
    chunk_ids: Annotated[list[Identifier], Field(min_length=1, max_length=30)]
    learning_objective: Text
    target_duration_seconds: Annotated[int, Field(ge=15, le=90)] = 40
    allow_generated_examples: bool = False


def _snapshot_pair(chunk, version, material):
    fingerprint = digest(
        json.dumps(
            {"content": chunk.content, "locator": chunk.locator}, sort_keys=True, ensure_ascii=False
        )
    )
    return {
        "chunk_id": chunk.id,
        "material_id": material.id,
        "material_revision": material.revision,
        "version_id": version.id,
        "version_sha256": version.sha256,
        "fingerprint": fingerprint,
    }, {"source_id": chunk.id, "text": chunk.content, "locator": chunk.locator}


def source_snapshots(session, course_id, chunk_ids, *, published=False):
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    from lerny.weekly_content import published_version_ids
    allowed = published_version_ids(session, course_id) if published else None
    if published and not allowed:
        return {}
    rows = session.execute(
        select(Chunk, MaterialVersion, Material)
        .options(defer(MaterialVersion.extraction_report), defer(MaterialVersion.extracted_text))
        .join(MaterialVersion, Chunk.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id)
        .where(
            Chunk.id.in_(ids),
            Material.course_id == course_id,
            Material.deleted.is_(False),
            Material.visibility == "public",
            Material.internal_use == "none",
            Material.kind != "answer",
            MaterialVersion.id.in_(allowed) if published else Material.active_version_id == MaterialVersion.id,
            MaterialVersion.status == "ready",
        )
        .execution_options(populate_existing=True)
    ).all()
    return {chunk.id: _snapshot_pair(chunk, version, material) for chunk, version, material in rows}


def source_snapshot(session, course_id, chunk_id, *, published=False):
    return source_snapshots(session, course_id, [chunk_id], published=published).get(chunk_id, (None, None))


def snapshot_is_current(session, course, payload):
    session.refresh(course)
    concept = session.get(Concept, payload["concept_id"], populate_existing=True)
    if (
        course.access_epoch != payload["access_epoch"]
        or concept is None
        or concept.course_id != course.id
        or concept.revision != payload["concept_revision"]
    ):
        return False
    return all(
        source_snapshot(session, course.id, old["chunk_id"])[0] == old for old in payload["sources"]
    )


def get_request(session, actor, course_id, request_id, lock=False):
    course = staff_access(session, actor, course_id)
    query = select(Job).where(
        Job.id == request_id, Job.course_id == course_id, Job.kind == "lecture_spec"
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    job = session.scalar(query)
    if job is None:
        deny(404, "강의 명세 요청을 찾을 수 없습니다.")
    return course, job


@router.get("/lecture-specs/schema")
def schema(actor: Actor):
    return LectureSpec.model_json_schema()


@router.post("/courses/{course_id}/lecture-spec-requests", status_code=201)
def create_request(course_id: str, body: CreateRequest, session: Db, actor: Actor):
    course = staff_access(session, actor, course_id)
    concept = session.get(Concept, body.concept_id)
    if not concept or concept.course_id != course_id:
        deny(404, "이 과목의 개념을 선택해 주세요.")
    if len(body.chunk_ids) != len(set(body.chunk_ids)):
        deny(422, "중복된 근거 ID입니다.")
    sources, source_texts = [], []
    for chunk_id in body.chunk_ids:
        snapshot, source = source_snapshot(session, course_id, chunk_id)
        if snapshot is None:
            deny(422, "현재 공개된 활성 자료의 근거만 사용할 수 있습니다.")
        sources.append(snapshot)
        source_texts.append(source)
    request_id = uid()
    payload = {
        "schema_version": "1.0",
        "request_id": request_id,
        "concept_id": concept.id,
        "concept_revision": concept.revision,
        "source_snapshot_id": uid(),
        "language": "ko-KR",
        "learning_objective": body.learning_objective,
        "target_duration_seconds": body.target_duration_seconds,
        "allow_generated_examples": body.allow_generated_examples,
        "presentation_profile": presentation_profile(),
        "allowed_source_ids": body.chunk_ids,
        "allowed_concept_ids": [concept.id],
        "access_epoch": course.access_epoch,
        "sources": sources,
    }
    job = Job(
        id=request_id,
        owner_id=actor.id,
        course_id=course_id,
        kind="lecture_spec",
        status="awaiting_input",
        payload=payload,
    )
    session.add(job)
    session.commit()
    return {
        "request_id": request_id,
        "status": job.status,
        "generation_input": {
            k: v for k, v in payload.items() if k not in ("access_epoch", "sources")
        },
        "sources": source_texts,
        "render_allowed": False,
    }


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError("non-finite JSON number")


@router.post("/courses/{course_id}/lecture-spec-requests/{request_id}/validate")
async def receive(course_id: str, request_id: str, request: Request, session: Db, actor: Actor):
    # Authorization precedes body consumption. Bound streaming payloads as well as Content-Length.
    get_request(session, actor, course_id, request_id)
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > MAX_BODY_BYTES:
            deny(413, "JSON은 256 KiB 이하여야 합니다.")
    try:
        data = json.loads(
            body.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        return JSONResponse(
            status_code=400, content={"validation": report([{"code": "INVALID_JSON", "path": ""}])}
        )
    course, job = get_request(session, actor, course_id, request_id, lock=True)
    if not snapshot_is_current(session, course, job.payload):
        return JSONResponse(
            status_code=409,
            content={
                "validation": report(
                    [{"code": "STALE_SOURCE_SNAPSHOT", "path": "source_snapshot_id"}]
                )
            },
        )
    spec, validation = validate_spec(data, job.payload)
    job.status = "checked" if validation["status"] == "needs_content_review" else "held"
    # Keep only schema- and reference-valid specs; never persist rejected raw model output.
    job.result = {
        "validation": validation,
        "spec": spec.model_dump(exclude_none=True) if validation["structure_valid"] else None,
    }
    session.commit()
    return JSONResponse(
        status_code=200 if validation["structure_valid"] else 422,
        content={"request_id": job.id, **job.result},
    )


@router.get("/courses/{course_id}/lecture-spec-requests/{request_id}")
def read_request(course_id: str, request_id: str, session: Db, actor: Actor):
    course, job = get_request(session, actor, course_id, request_id)
    if not snapshot_is_current(session, course, job.payload):
        return JSONResponse(
            status_code=409,
            content={
                "request_id": job.id,
                "spec": None,
                "validation": report(
                    [{"code": "STALE_SOURCE_SNAPSHOT", "path": "source_snapshot_id"}]
                ),
            },
        )
    return {
        "request_id": job.id,
        "status": job.status,
        "render_allowed": False,
        "result": job.result,
    }
