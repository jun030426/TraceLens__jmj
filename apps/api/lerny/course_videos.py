"""Shared, source-authorized concept videos; only the durable worker contacts HeyGen."""


from fastapi import APIRouter
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from lerny import storage
from lerny.config import settings
from lerny.heygen_site_video import compile_site_plan
from lerny.models import ConceptVideo, Job, Material, MaterialVersion, Section, now, uid
from lerny.security import Actor, Db, course_access, deny, staff_access

router = APIRouter(prefix="/api/v1")


def render_block_reason(session):
    from lerny.models import ContentGeneration
    return session.scalar(select(ConceptVideo.error_code).join(ContentGeneration,
        ContentGeneration.id == ConceptVideo.generation_id).where(
        ContentGeneration.status == 'draft', ConceptVideo.status.in_(['failed','held']),
        ConceptVideo.error_code.in_(['HEYGEN_API_CREDITS_REQUIRED','HEYGEN_AUTH_REQUIRED']))
        .order_by(ConceptVideo.created_at).limit(1))


def credit_blocked(session):
    return render_block_reason(session) is not None


def current_source(session, video):
    if not video:
        return None
    version = session.get(MaterialVersion, video.version_id)
    material = session.get(Material, version.material_id) if version else None
    from lerny.weekly_content import source_allowed
    return material if (material and material.course_id == video.course_id and not material.deleted
        and material.visibility == "public" and material.internal_use == "none" and version.status == "ready"
        and source_allowed(session,video,version)) else None


def enqueue(session, job, version, concept, position, *, description=None):
    generation_id=job.payload.get("generation_id")
    if session.scalar(select(ConceptVideo.id).where(ConceptVideo.generation_id == generation_id,
                                                   ConceptVideo.concept_id == concept.id)):
        return
    video = ConceptVideo(id=uid(), course_id=job.course_id, version_id=version.id,
                         generation_id=generation_id,
                         concept_id=concept.id, owner_id=job.owner_id, position=position, title=concept.name)
    session.add(video)
    session.flush()
    from lerny.models import Course
    course = session.get(Course, job.course_id)
    draft = Job(owner_id=job.owner_id, course_id=job.course_id, kind="narration_lesson", payload={
        "generation_id":generation_id,
        "concept_id": concept.id, "concept_revision": concept.revision, "source_version_id": version.id,
        "learning_objective": description or concept.description, "target_duration_seconds": 50,
        "access_epoch": course.access_epoch, "source_snapshot_id": uid(), "sources": [], "video_id": video.id})
    if generation_id:
        from lerny.models import ContentGeneration
        draft.payload={**draft.payload,"source_version_ids":[s['version_id'] for s in session.get(ContentGeneration,generation_id).sources]}
    session.add(draft)
    session.flush()
    video.script_job_id = draft.id


def accept_draft(session, job, result):
    video = session.get(ConceptVideo, job.payload.get("video_id")) if job.payload.get("video_id") else None
    if not video:
        return
    if not current_source(session, video):
        raise ValueError("SOURCE_REVOKED")
    if result.get("validation") != "model_reviewed":
        raise ValueError("SCRIPT_VALIDATION_FAILED")
    # Replayed narration completion must never overwrite an accepted provider receipt.
    if video.provider_session_id or video.provider_video_id:
        return
    video.script = result["draft"]
    video.request = compile_site_plan(result["draft"]["lesson"])
    video.status, video.next_poll_at = "queued", now()
    from lerny.lecture_slides import enqueue as enqueue_slides
    enqueue_slides(session, video)


def view(session, video, staff=False):
    from lerny.weekly_content import artifact_published
    if not staff and not artifact_published(session,video):
        return None
    material = current_source(session, video)
    if not material:
        return None
    status = video.status
    if status == "script_pending":
        job = session.get(Job, video.script_job_id)
        if job and job.status in {"failed", "waiting_ai", "cancelled"}:
            status = job.status
    result = {"id": video.id, "title": video.title, "concept_id": video.concept_id,
              "material_id": material.id, "source_title": material.title, "week": material.week,
              "position": video.position, "status": status, "duration_seconds": video.duration_seconds,
              "play_url": f"/api/v1/concept-videos/{video.id}/file" if status == "ready" else None}
    from lerny.lecture_poster import poster_receipt
    result['poster_url'] = f'/api/v1/concept-videos/{video.id}/poster' if poster_receipt(session,video) else None
    if staff:
        result.update(error_code=video.error_code, script=video.script)
        from lerny.models import ContentGeneration
        from lerny.weekly_content import video_included
        generation = session.get(ContentGeneration, video.generation_id) if video.generation_id else None
        result["included"] = not generation or video_included(generation, video)
        if status == 'queued' and (reason := render_block_reason(session)):
            result.update(status='waiting_credits' if reason == 'HEYGEN_API_CREDITS_REQUIRED' else 'held', error_code=reason)
        job = session.get(Job, video.script_job_id) if video.script_job_id else None
        if job and job.error_code:
            result["error_code"] = job.error_code
    return result


@router.get("/sections/{section_id}/concept-videos")
def catalogue(section_id: str, session: Db, actor: Actor):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    course_access(session, actor, section.course_id)
    rows = session.scalars(select(ConceptVideo).join(MaterialVersion, ConceptVideo.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id).where(ConceptVideo.course_id == section.course_id)
        .order_by(Material.week, Material.created_at, ConceptVideo.position, ConceptVideo.id))
    items, positions = [], {}
    for row in rows:
        item = view(session, row)
        if item:
            positions[item["week"]] = positions.get(item["week"], 0) + 1
            item["position"] = positions[item["week"]]
            items.append(item)
    return {"items": items, "shared": True}


@router.get("/courses/{course_id}/concept-videos")
def staff_catalogue(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    rows = session.scalars(select(ConceptVideo).where(ConceptVideo.course_id == course_id)
                          .order_by(ConceptVideo.created_at))
    return {"items": [item for row in rows if (item := view(session, row, True))]}


@router.get("/concept-videos/{video_id}/file")
def video_file(video_id: str, session: Db, actor: Actor):
    video = session.get(ConceptVideo, video_id)
    if not video or video.status != "ready" or not current_source(session, video):
        deny(404)
    course_access(session, actor, video.course_id)
    from lerny.weekly_content import artifact_published
    if actor.role == "student" and not artifact_published(session,video):
        deny(404)
    path = storage.request("POST", "/object/sign/" + storage.object_path(video.object_key),
                           json={"expiresIn": 300}).json()["signedURL"]
    if not path.startswith("/object/sign/"):
        deny(503)
    return RedirectResponse(settings().supabase_url.rstrip("/") + "/storage/v1" + path,
                            headers={"Cache-Control": "private, no-store"})


@router.get('/concept-videos/{video_id}/poster')
def video_poster(video_id: str, session: Db, actor: Actor):
    video=session.get(ConceptVideo,video_id)
    if not video or not current_source(session,video):deny(404)
    course_access(session,actor,video.course_id)
    from lerny.weekly_content import artifact_published
    if actor.role=='student' and (video.status!='ready' or not artifact_published(session,video)):
        deny(404)
    from lerny.lecture_poster import poster_receipt
    from lerny.google_slides_client import fingerprint
    receipt=poster_receipt(session,video)
    if not receipt:deny(404)
    raw=storage.download(receipt['object_key'],2*1024*1024)
    if fingerprint(raw)!=receipt['sha256']:deny(409)
    return Response(raw,media_type='image/webp',headers={'Cache-Control':'private, no-store'})


@router.post("/courses/{course_id}/concept-videos/{video_id}/retry")
def retry(course_id: str, video_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    video = session.scalar(select(ConceptVideo).where(ConceptVideo.id == video_id).with_for_update())
    if not video or video.course_id != course_id or not current_source(session, video):
        deny(404)
    if video.generation_id:
        from lerny.models import ContentGeneration
        from lerny.weekly_content import is_current
        generation=session.get(ContentGeneration,video.generation_id)
        if generation.status != "draft" or not is_current(session,generation):
            deny(409,"주차 자료를 확인한 뒤 다시 생성해 주세요.")
        if (generation.options or {}).get("video_mode") in {"ready_only", "none"}:
            deny(409, "새 영상 제작을 제외한 상태예요. 영상 제작을 재개하려면 주차 검토에서 전체 영상 준비로 전환해 주세요.")
    submitted = bool(video.provider_session_id or video.provider_video_id)
    if video.status in {"submitting", "needs_attention"} and not submitted:
        deny(409, "생성 요청의 접수 여부를 먼저 확인해야 중복 생성을 막을 수 있어요.")
    if (video.status == 'failed' and video.error_code == 'HEYGEN_API_CREDITS_REQUIRED'
            and video.provider_video_id and not video.provider_session_id):
        # Only this explicit instructor action may retry a confirmed terminal
        # credit failure. Preserve its receipt in the audit log and reuse assets.
        job = session.get(Job, video.script_job_id) if video.script_job_id else None
        if not job or job.status != 'succeeded' or not video.script:
            deny(409, '검증된 대본이 필요해요.')
        from lerny.heygen_site_video import checked_request
        checked_request(video.request)
        from lerny.courses import audit
        audit(session, actor, 'video_credit_failure_retried', video.id,
              {'previous_provider_video_id': video.provider_video_id,
               'previous_error_code': video.error_code, 'validated_script_reused': True})
        video.provider_video_id = None
        video.status, video.next_poll_at, video.error_code = 'queued', now(), None
    elif submitted and video.status not in {"failed", "cancelled", "ready"}:
        video.next_poll_at, video.status, video.error_code = now(), "processing", None
    elif (not submitted and video.status == "held"
          and video.error_code in {"VIDEO_PREPARATION_FAILED", "HEYGEN_AUTH_REQUIRED", "HEYGEN_API_CREDITS_REQUIRED"}):
        if video.error_code != "VIDEO_PREPARATION_FAILED":
            from lerny.courses import audit
            config = settings()
            if not (config.heygen_calls_enabled and config.heygen_rendering_enabled and config.heygen_api_key.get_secret_value()):
                deny(409, "영상 API 연결과 크레딧을 확인한 뒤 직접 다시 요청해 주세요.")
            audit(session, actor, "video_provider_hold_retried", video.id,
                  {"previous_error_code": video.error_code, "request_reused": True})
        video.status, video.next_poll_at, video.error_code = "queued", now(), None
    elif video.status in {"script_pending", "held", "failed"} and not submitted:
        job = session.get(Job, video.script_job_id)
        if job and job.status == "failed":
            job.status, job.error_code = "queued", None
            from lerny.models import Course
            job.payload = {**job.payload, "access_epoch": session.get(Course, course_id).access_epoch,
                           "sources": [], "_ai_generation": job.payload.get("_ai_generation", 0) + 1}
            video.status, video.error_code = "script_pending", None
        else:
            deny(409, "기존 작업 상태를 먼저 확인해 주세요.")
    else:
        deny(409, "이 작업은 자동 재요청할 수 없어요.")
    session.commit()
    return view(session, video, True)
