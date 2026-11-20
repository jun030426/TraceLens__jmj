"""Durable HeyGen submissions and recoverable polling, independent of web requests."""

import re
import time
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from lerny import storage
from lerny.config import settings
from lerny.course_videos import current_source, credit_blocked
from lerny.db import engine
from lerny.heygen_site_video import checked_request
from lerny.heygen_video_agent import API_ROOT, AgentError, VideoAgentRun
from lerny.models import ConceptVideo, ContentGeneration, now, uid


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value):
        raise ValueError("INVALID_PROVIDER_ID")
    return value


def generation_active(session, row):
    # Superseded drafts must never start a new billable render.
    if not row.generation_id:
        return False
    from lerny.models import ContentGeneration
    from lerny.weekly_content import is_current
    generation=session.get(ContentGeneration,row.generation_id,populate_existing=True)
    return bool(generation and generation.status=="draft" and is_current(session,generation))


def claim(session):
    from lerny.operations import enabled, state, touch
    control = state(session, lock=True)
    touch(session, "video")
    if control.server_hold:
        session.commit()
        return None
    # Serialize the global capacity decision across worker processes.
    session.execute(text("SELECT pg_advisory_xact_lock(1736224151)"))
    expired = or_(ConceptVideo.lease_until.is_(None), ConceptVideo.lease_until < now())
    # Persisted pre-POST state without a receipt must never be submitted twice.
    uncertain = list(session.scalars(select(ConceptVideo).where(
        ConceptVideo.status == "submitting", expired).with_for_update(skip_locked=True)))
    for row in uncertain:
        if row.provider_session_id or row.provider_video_id:
            row.status, row.error_code = "processing", None
        else:
            row.status, row.error_code = "needs_attention", "SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT"
    inflight = session.scalar(select(func.count()).select_from(ConceptVideo).where(
        ConceptVideo.status.in_(["submitting", "processing", "storing"])))
    states = ["processing", "storing"] + (["queued"] if inflight < 2 and enabled(control, "videos")
                                           and settings().heygen_rendering_enabled and settings().heygen_calls_enabled
                                           and settings().heygen_api_key.get_secret_value() and not credit_blocked(session) else [])
    # Preserve deferred requests/scripts without ever submitting a new render.
    # Already accepted receipts still finish polling and storage.
    deferred_generations = select(ContentGeneration.id).where(
        ContentGeneration.options["video_mode"].as_string().in_(["ready_only", "none"]))
    row = session.scalar(select(ConceptVideo).where(ConceptVideo.status.in_(states), expired,
        or_(ConceptVideo.status != "queued", ConceptVideo.generation_id.not_in(deferred_generations)),
        or_(ConceptVideo.next_poll_at.is_(None), ConceptVideo.next_poll_at <= now()))
        .order_by(ConceptVideo.next_poll_at, ConceptVideo.created_at).with_for_update(skip_locked=True).limit(1))
    if not row:
        session.commit()
        return None
    if not current_source(session, row) or not generation_active(session,row):
        row.status, row.error_code = "revoked", "SOURCE_REVOKED"
        session.commit()
        return None
    action = ("submit" if row.status == "queued"
              and not (row.provider_session_id or row.provider_video_id) else "poll")
    row.lease_token, row.lease_until = uid(), now() + timedelta(minutes=5)
    if action == "submit":
        row.status = "submitting"
    elif row.status == "queued":
        row.status = "processing"
    touch(session, "video", busy=True)
    session.commit()
    return {"id": row.id, "lease": row.lease_token, "action": action, "request": row.request,
            "session_id": row.provider_session_id, "video_id": row.provider_video_id}


def update(item, **values):
    with Session(engine()) as session:
        row = session.scalar(select(ConceptVideo).where(
            ConceptVideo.id == item["id"], ConceptVideo.lease_token == item["lease"],
            ConceptVideo.lease_until > now()).with_for_update())
        if not row:
            return False
        if not current_source(session, row) or not generation_active(session,row):
            row.status, row.error_code = "revoked", "SOURCE_REVOKED"
        else:
            for key, value in values.items():
                setattr(row, key, value)
        row.lease_token, row.lease_until = None, None
        session.commit()
        return True


def get_data(client, path):
    response = client.get(API_ROOT + path)
    response.raise_for_status()
    data = response.json()["data"]
    if not isinstance(data, dict):
        raise ValueError("INVALID_PROVIDER_RESPONSE")
    return data


def terminal_error(data):
    if data.get('failure_code') == 'MOVIO_PAYMENT_INSUFFICIENT_CREDIT':
        return 'HEYGEN_API_CREDITS_REQUIRED'
    return 'PROVIDER_TERMINAL_FAILURE'


def permanent_provider_error(error):
    """Provider authentication/billing errors require operator action, not polling retries.

    A CDN/storage 403 is not evidence that the HeyGen API key is invalid.
    Never persist provider bodies, which may contain credentials or signed URLs.
    """
    response = error.response
    if response.request.url.host != httpx.URL(API_ROOT).host:
        return None
    if response.status_code in {401, 403}:
        return 'HEYGEN_AUTH_REQUIRED'
    if response.status_code == 402:
        return 'HEYGEN_API_CREDITS_REQUIRED'
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    sections = [body, *[body[k] for k in ('data','error') if isinstance(body.get(k),dict)]]
    if any(section.get(k) == 'MOVIO_PAYMENT_INSUFFICIENT_CREDIT'
           for section in sections for k in ('code','failure_code')):
        return 'HEYGEN_API_CREDITS_REQUIRED'
    return None


def persist_prepared(item, body):
    """Persist exact assets/request before the billable POST; keep the active lease."""
    with Session(engine()) as session:
        row = session.scalar(select(ConceptVideo).where(
            ConceptVideo.id == item["id"], ConceptVideo.lease_token == item["lease"],
            ConceptVideo.lease_until > now()).with_for_update())
        if (not row or row.provider_video_id or row.provider_session_id
                or not current_source(session, row) or not generation_active(session, row)):
            return False
        generation = session.get(ContentGeneration, row.generation_id, populate_existing=True)
        if (generation.options or {}).get("video_mode", "all") != "all":
            # The instructor may exclude video after the worker claimed it.
            row.status, row.error_code = "queued", None
            row.lease_token, row.lease_until = None, None
            session.commit()
            return False
        row.request = body
        session.commit()
        return True


def render_matches(client, vid):
    """A provider fallback must not be presented as an Avatar V/1080p success."""
    data = get_data(client, "/v3/videos/" + vid + "/scenes")
    scenes = data.get("scenes") or []
    avatars = [element for scene in scenes for element in scene.get("elements", [])
               if element.get("type") == "avatar"]
    from lerny.heygen_lecture_profile import LERNY_LOOK_ID, LERNY_VOICE_ID
    speech = [line for scene in scenes for line in scene.get("script", [])]
    return bool(data.get("video", {}).get("resolution") == "1080p" and avatars and speech
                and all(a.get("engine") == "avatar_v" and a.get("avatar_id") == LERNY_LOOK_ID
                        for a in avatars)
                and all(s.get("type") == "text" and s.get("voice_id") == LERNY_VOICE_ID
                        for s in speech))


def process(item, client):
    if item["action"] == "submit":
        # A saved receipt is authoritative even if an operator accidentally requeues it.
        if item.get("session_id") or item.get("video_id"):
            return process({**item, "action": "poll"}, client)
        if not settings().heygen_rendering_enabled:
            update(item, status="queued", error_code="HEYGEN_RENDERING_PAUSED")
            return
        body = item["request"]
        try:
            if body.get("type") == "lerny_studio_plan":
                from lerny.lecture_slides import prepare_video_request
                body = prepare_video_request(item["id"], client)
        except httpx.HTTPStatusError as exc:
            code = permanent_provider_error(exc)
            update(item, status="held", error_code=code or "VIDEO_PREPARATION_FAILED", next_poll_at=None)
            return
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
            update(item, status="held", error_code="VIDEO_PREPARATION_FAILED")
            return
        try:
            body = checked_request(body)
        except ValueError:
            update(item, status="held", error_code="VIDEO_PROFILE_REVIEW_REQUIRED")
            return
        if not persist_prepared(item, body):
            return
        try:
            # No transport retry for this billable POST. The database receipt is authoritative.
            response = client.post(API_ROOT + "/v3/videos", json=body)
            response.raise_for_status()
            data = response.json()["data"]
            vid = identifier(data["video_id"])
            update(item, status="processing", provider_video_id=vid,
                   next_poll_at=now() + timedelta(seconds=30), error_code=None)
        except httpx.HTTPStatusError as exc:
            code = permanent_provider_error(exc)
            update(item, status="held" if code else "needs_attention",
                   error_code=code or "SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT", next_poll_at=None)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            update(item, status="needs_attention", error_code="SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT")
        return
    vid = item.get("video_id")
    # Historical Video Agent receipts keep their original poll path, never a new POST.
    if item.get("session_id"):
        sid = identifier(item["session_id"])
        data = get_data(client, "/v3/video-agents/" + sid)
        if data.get("session_id") != sid:
            raise ValueError("SESSION_ID_MISMATCH")
        if data.get("status") in {"failed", "cancelled", "stopped"}:
            update(item, status="failed", error_code=terminal_error(data))
            return
        vid = data.get("video_id") or vid
        if not vid:
            if data.get("status") not in {"thinking", "generating"}:
                update(item, status="needs_attention", error_code="PROVIDER_REQUIRES_REVIEW")
            else:
                update(item, next_poll_at=now() + timedelta(seconds=30))
            return
    if not vid:
        update(item, status="needs_attention", error_code="SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT")
        return
    vid = identifier(vid)
    if item.get("video_id") and item["video_id"] != vid:
        raise ValueError("VIDEO_ID_CHANGED")
    video = get_data(client, "/v3/videos/" + vid)
    if video.get("status") in {"failed", "cancelled"}:
        update(item, status="failed", provider_video_id=vid, error_code=terminal_error(video))
        return
    if video.get("status") != "completed":
        update(item, provider_video_id=vid, next_poll_at=now() + timedelta(seconds=30))
        return
    if not item.get("session_id") and not render_matches(client, vid):
        update(item, status="held", provider_video_id=vid, error_code="VIDEO_RENDER_PROFILE_MISMATCH")
        return
    with TemporaryDirectory(prefix="lerny-video-") as directory:
        run = VideoAgentRun(Path(directory))
        # A separate unauthenticated media client prevents API-key leakage to a CDN.
        with httpx.Client(timeout=90, trust_env=False, follow_redirects=False) as media:
            size, checksum = run._download(media, video.get("video_url"))
        bucket = storage.request("GET", "/bucket/" + settings().storage_bucket).json()
        if size > (bucket.get("file_size_limit") or 50 * 1024 * 1024):
            update(item, status="held", provider_video_id=vid, error_code="VIDEO_STORAGE_SIZE_LIMIT")
            return
        with Session(engine()) as session:
            row = session.get(ConceptVideo, item["id"])
            if not current_source(session, row):
                update(item, status="revoked", error_code="SOURCE_REVOKED")
                return
        key = f"lecture-videos/{item['id']}/{checksum}.mp4"
        storage.request("POST", "/object/" + storage.object_path(key), content=run.video.read_bytes(),
                        headers={"Content-Type": "video/mp4", "x-upsert": "true"})
        duration = video.get("duration")
        update(item, status="ready", provider_video_id=vid, object_key=key,
               duration_seconds=duration if isinstance(duration, (float, int)) and duration > 0 else None,
               error_code=None)


def run_once():
    config = settings()
    if not (config.automatic_learning_enabled and config.heygen_calls_enabled and config.heygen_api_key.get_secret_value()):
        from lerny.operations import finished
        finished("video")
        return False
    with Session(engine()) as session:
        item = claim(session)
    if not item:
        return False
    try:
        with httpx.Client(timeout=120, trust_env=False, follow_redirects=False,
                          headers={"x-api-key": config.heygen_api_key.get_secret_value()}) as client:
            process(item, client)
    except httpx.HTTPStatusError as exc:
        code = permanent_provider_error(exc)
        if code:
            update(item, status="held", error_code=code, next_poll_at=None)
        else:
            update(item, error_code="VIDEO_STATUS_OR_STORAGE_RETRY", next_poll_at=now() + timedelta(seconds=60))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AgentError, storage.StorageUnavailable):
        update(item, error_code="VIDEO_STATUS_OR_STORAGE_RETRY", next_poll_at=now() + timedelta(seconds=60))
    finally:
        from lerny.operations import finished
        finished("video")
    return True


def main():
    if not settings().dedicated_worker:
        raise SystemExit("Dedicated worker configuration required")
    while True:
        try:
            worked = run_once()
        except Exception as exc:
            print("Video worker retry:", type(exc).__name__, flush=True)
            worked = False
        if not worked:
            time.sleep(5)


if __name__ == "__main__":
    main()
