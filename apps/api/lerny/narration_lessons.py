"""Current authorized RAG evidence -> cited narration -> fixed Lerny HeyGen request.

Separate from LectureSpec 1.0. This prepares a request; it never purchases a video.
"""

from typing import Literal

from fastapi import APIRouter, Header
from pydantic import Field
from sqlalchemy import select

from lerny.config import settings
from lerny.evaluation import review_references
from lerny.gemini_provider import available
from lerny.heygen_lecture_profile import NarrationLesson
from lerny.heygen_site_video import PROFILE_ID, compile_site_plan, presentation_settings
from lerny.heygen_slides import AssetId, Script, compile_studio
from lerny.jobs import idempotent
from lerny.lecture_contract import Identifier, StrictModel
from lerny.lecture_specs import snapshot_is_current, source_snapshot
from lerny.models import Concept, Job, User, uid
from lerny.rag_answers import Citation, citations_valid
from lerny.retrieval import internal_validation_context, search_public
from lerny.security import Actor, Db, deny, staff_access

router = APIRouter(prefix="/api/v1", tags=["narration-lessons"])


class CreateLesson(StrictModel):
    concept_id: Identifier
    learning_objective: str = Field(min_length=1, max_length=1000)
    target_duration_seconds: int = Field(default=65, ge=15, le=90)


class LessonCitation(Citation):
    target: str = Field(pattern=r"^/lesson/(narration|key_facts)/(0|[1-9][0-9]*)$")


class LessonDraft(StrictModel):
    schema_version: Literal["lerny.lesson-draft.v1"]
    request_id: Identifier
    source_snapshot_id: Identifier
    generation_status: Literal["draft", "insufficient_evidence", "conflicting_evidence"]
    lesson: NarrationLesson | None
    citations: list[LessonCitation] = Field(max_length=180)
    reason: str = Field(max_length=1000)


@router.get("/narration-lessons/schema")
def lesson_schema(actor: Actor):
    return LessonDraft.model_json_schema()


@router.post("/courses/{course_id}/narration-lessons", status_code=202)
def create(
    course_id: str,
    body: CreateLesson,
    session: Db,
    actor: Actor,
    idempotency_key: str | None = Header(default=None),
):
    course = staff_access(session, actor, course_id)
    concept = session.get(Concept, body.concept_id)
    if not concept or concept.course_id != course_id:
        deny(404)
    if settings().ai_provider != "gemini":
        deny(409, "Gemini 공급자를 선택한 로컬 환경에서 실행해 주세요.")
    try:
        available()
    except ValueError as exc:
        deny(409, str(exc))

    def make():
        job = Job(
            owner_id=actor.id,
            course_id=course_id,
            kind="narration_lesson",
            payload={
                **body.model_dump(),
                "concept_revision": concept.revision,
                "access_epoch": course.access_epoch,
                "source_snapshot_id": uid(),
                "sources": [],
            },
        )
        session.add(job)
        session.flush()
        return {
            "job_id": job.id,
            "status": "queued",
            "poll_url": f"/api/v1/courses/{course_id}/narration-lessons/{job.id}",
        }

    return idempotent(
        session,
        actor,
        "narration_lesson:" + course_id,
        idempotency_key,
        {
            **body.model_dump(),
            "concept_revision": concept.revision,
            "access_epoch": course.access_epoch,
        },
        make,
    )


@router.get("/courses/{course_id}/narration-lessons/{job_id}")
def read(course_id: str, job_id: str, session: Db, actor: Actor):
    course = staff_access(session, actor, course_id)
    job = session.scalar(
        select(Job).where(
            Job.id == job_id, Job.course_id == course_id, Job.kind == "narration_lesson"
        )
    )
    if not job:
        deny(404)
    if not snapshot_is_current(session, course, job.payload):
        deny(409, "자료 또는 개념이 변경되어 강의 대본을 다시 생성해야 합니다.")
    response = {
        "job_id": job.id,
        "status": job.status,
        "error_code": job.error_code,
        "result": job.result,
        "video_generated": False,
        "publication_allowed": False,
    }
    if (
        job.status == "succeeded"
        and job.result
        and job.result.get("validation") == "model_reviewed"
    ):
        response["video_plan"] = compile_site_plan(job.result["draft"]["lesson"])
        response["render_settings"] = presentation_settings()
    return response


class SlideBinding(StrictModel):
    asset_id: AssetId
    script: Script


class SlidePreview(StrictModel):
    slides: list[SlideBinding] = Field(min_length=1, max_length=50)


@router.post("/courses/{course_id}/narration-lessons/{job_id}/slides-preview")
def slides_preview(course_id: str, job_id: str, body: SlidePreview, session: Db, actor: Actor):
    current = read(course_id, job_id, session, actor)
    if not current.get("video_plan"):
        deny(409, "검증이 끝난 강의 대본이 필요합니다.")
    lesson = current["result"]["draft"]["lesson"]
    scripts = [slide.script for slide in body.slides]
    if " ".join(scripts).split() != " ".join(lesson["narration"]).split():
        deny(409, "슬라이드 발표자 노트와 검증된 강의 대본의 내용·순서가 다릅니다.")
    request = compile_studio(lesson["title"], [slide.asset_id for slide in body.slides], scripts)
    return {"heygen_request": request, "submitted": False, "publication_allowed": False}


def current_context(session, job):
    actor = session.get(User, job.owner_id, populate_existing=True)
    if not actor or not actor.active:
        raise ValueError("ACCESS_REVOKED")
    course = staff_access(session, actor, job.course_id)
    if job.payload.get("generation_id"):
        from lerny.weekly_content import generation_for_job
        generation_for_job(session,job)
        # Other weeks may change the course epoch; the exact weekly source set remains authoritative.
        job.payload={**job.payload,"access_epoch":course.access_epoch}
    if job.payload.get("video_id") and not job.payload.get("sources"):
        # Automatic jobs can wait behind another upload; take the snapshot when processing starts.
        from lerny.course_videos import current_source
        from lerny.models import ConceptVideo
        if not current_source(session, session.get(ConceptVideo, job.payload["video_id"])):
            raise ValueError("SOURCE_REVOKED")
        job.payload = {**job.payload, "access_epoch": course.access_epoch}
    if not snapshot_is_current(session, course, job.payload):
        raise ValueError("SOURCE_CHANGED")
    return session.get(Concept, job.payload["concept_id"], populate_existing=True)


def validate_draft(draft, job, concept, sources):
    if draft.request_id != job.id or draft.source_snapshot_id != job.payload["source_snapshot_id"]:
        raise ValueError("LECTURE_REQUEST_MISMATCH")
    if draft.generation_status != "draft":
        return None
    if (
        draft.lesson is None
        or draft.lesson.title != concept.name
        or draft.lesson.target_duration_seconds != job.payload["target_duration_seconds"]
    ):
        raise ValueError("LECTURE_REQUEST_MISMATCH")
    evidence = {s["source_id"]: s["text"] for s in sources}
    targets = {
        f"/lesson/{field}/{i}": value
        for field in ("narration", "key_facts")
        for i, value in enumerate(getattr(draft.lesson, field))
    }
    if {c.target for c in draft.citations} != set(targets) or not citations_valid(
        draft.citations, evidence
    ):
        raise ValueError("INVALID_CITATION")
    compile_site_plan(draft.lesson.model_dump())
    return [
        {
            "target": target,
            "text": text,
            "source_ids": list(
                dict.fromkeys(c.source_id for c in draft.citations if c.target == target)
            ),
        }
        for target, text in targets.items()
    ]


def narration_job(session, job):
    from lerny.worker import model_json

    if settings().ai_provider != "gemini":
        raise ValueError("PROVIDER_CHANGED")
    concept = current_context(session, job)
    scope = {"version_ids":job.payload["source_version_ids"]} if job.payload.get("generation_id") else (
        {"version_id": job.payload["source_version_id"]} if job.payload.get("source_version_id") else {})
    # A 50-second lesson needs the supporting explanation, not only a few matching
    # headings/OCR labels. Keep the same authorized immutable week scope, while
    # giving generation a bounded wider evidence set than a short chat answer.
    rows = search_public(session, job.course_id, concept.name + " " + job.payload["learning_objective"], limit=12, **scope)
    if not rows:
        result = {"validation": "held", "reason": "NO_PUBLIC_EVIDENCE", "profile": PROFILE_ID}
        from lerny.course_videos import accept_draft
        accept_draft(session, job, result)
        return result
    snapshots, sources = [], []
    for chunk, _, _ in rows:
        snapshot, source = source_snapshot(session, job.course_id, chunk.id)
        if snapshot is None:
            raise ValueError("SOURCE_CHANGED")
        snapshots.append(snapshot)
        sources.append(source)
    job.payload = {**job.payload, "sources": snapshots}

    def generate(prompt, schema):
        current_context(session, job)
        result = model_json(prompt, schema)
        current_context(session, job)
        return result

    from lerny.team_engine import narration_draft
    draft = narration_draft(rows, job, concept, generate)
    units = validate_draft(draft, job, concept, sources)
    from lerny.narration_evidence import review_narration
    from lerny.narration_repair import NarrationValidationError, finish_length, repair_evidence
    issues = []
    citations = review_narration(units, sources, generate, issues=issues) if units is not None else None
    for repair_attempt in range(2):
        if (not job.payload.get('video_id') or citations is not None or units is None
                or not issues or any(not i.get('target') for i in issues)):
            break
        draft = repair_evidence(draft, issues, sources, generate,
            job.payload.get('_narration_repair_round', 0), repair_attempt + 1)
        if draft.lesson.target_duration_seconds == 50:
            draft.lesson.narration = finish_length(draft.lesson.narration, rows, concept.name, generate,
                job.payload.get('_narration_repair_round', 0))
        # Initial citations only check allowed source membership. Every rewritten
        # statement must receive a fresh full semantic review before acceptance.
        units = validate_draft(draft, job, concept, sources)
        issues = []
        citations = review_narration(units, sources, generate, issues=issues)
    passed = citations is not None
    if not passed and job.payload.get('video_id'):
        raise NarrationValidationError('SCRIPT_VALIDATION_FAILED', issues or [{
            'code':'NO_PUBLIC_EVIDENCE','message':'대본을 완성할 공개 원문 근거가 부족해요.'}])
    if passed:
        draft.citations = [LessonCitation.model_validate(c) for c in citations]
        units = validate_draft(draft, job, concept, sources)
    if passed:
        references = internal_validation_context(
            session, job.course_id, concept.name + " " + job.payload["learning_objective"],
            source_ids=[c.id for c, _, _ in rows],
        )
        passed = review_references(units, references, generate)
        if not passed and job.payload.get('video_id'):
            raise NarrationValidationError('SCRIPT_VALIDATION_FAILED', [{
                'code':'NARRATION_REFERENCE_CONFLICT','message':'대본과 교수자 검증 기준의 일치 여부를 확인하지 못했어요.'}])
    current_context(session, job)
    result = {
        "draft": draft.model_dump(),
        "validation": "model_reviewed" if passed else "held",
        "profile": PROFILE_ID,
        "video_generated": False,
        "review_limit": "Same-model semantic review; human video review remains necessary.",
    }
    from lerny.course_videos import accept_draft
    accept_draft(session, job, result)
    return result
