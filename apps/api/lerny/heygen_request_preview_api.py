"""Read-only staff preview of a stored lecture; never creates jobs or contacts HeyGen."""

from fastapi import APIRouter
from sqlalchemy import select

from lerny.heygen_request_preview import PreviewOptions, PromptTooLong, compile_preview
from lerny.lecture_grounding import REVIEW_VERSION, spec_hash
from lerny.lecture_specs import get_request, snapshot_is_current
from lerny.models import Job
from lerny.security import Actor, Db, deny

router = APIRouter(prefix="/api/v1/courses/{course_id}/lecture-spec-requests")


@router.post("/{request_id}/heygen-preview")
def preview(course_id: str, request_id: str, body: PreviewOptions, session: Db, actor: Actor):
    course, parent = get_request(session, actor, course_id, request_id)
    if not snapshot_is_current(session, course, parent.payload):
        deny(409, "자료가 변경됐습니다. 새 강의 명세 요청이 필요합니다.")
    if not parent.result or not parent.result.get("spec"):
        deny(409, "구조 검증을 통과한 초안이 필요합니다.")
    spec = parent.result["spec"]
    fingerprint = spec_hash(spec)
    # Never accept a client's claim of successful grounding or ignore a stored negative result.
    query = (
        select(Job)
        .where(
            Job.course_id == course_id,
            Job.kind == "lecture_grounding",
            Job.payload["lecture_request_id"].as_string() == parent.id,
            Job.payload["spec_hash"].as_string() == fingerprint,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    latest = session.scalar(query.limit(1))
    completed = session.scalar(query.where(Job.status == "succeeded").limit(1))
    grounding = {
        "job_id": latest.id if latest else None,
        "job_status": latest.status if latest else "not_requested",
        "semantic_grounding": "not_checked",
    }
    if completed and completed.result:
        result = completed.result
        current = (
            result.get("spec_hash") == fingerprint
            and result.get("source_snapshot_id") == spec["source_snapshot_id"]
            and result.get("review_version") == REVIEW_VERSION
        )
        outcome = result.get("semantic_grounding") if current else "outdated_review"
        if current and outcome != "model_supported":
            deny(409, "내용 검증에서 보류된 대본입니다. 수정 후 다시 검증해 주세요.")
        # A retry must not hide a known negative review of the same text. A pending retry
        # also must not be presented as already approved based on an older positive review.
        if latest.id == completed.id:
            grounding["semantic_grounding"] = outcome
    try:
        result = compile_preview(spec, parent.payload, body)
    except PromptTooLong:
        deny(422, "Video Agent 제작 지시가 10,000자를 초과합니다. 대본과 설명 자료를 줄여 주세요.")
    except ValueError:
        deny(409, "구조 검증을 통과한 초안이 필요합니다.")
    result["request_id"] = request_id
    result["spec_hash"] = fingerprint
    result["validation"] = {
        "structure_valid": True,
        "grounding": grounding,
        "human_review": "not_recorded",
    }
    if grounding["semantic_grounding"] != "model_supported":
        result["blockers"].append("GROUNDING_NOT_COMPLETED")
    return result
