"""Authenticated section playback of local MP4s; no provider calls or generation."""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from lerny.config import settings
from lerny.heygen_pilot import Pilot, PilotError
from lerny.jobs import section_student
from lerny.lecture_playback import LocalLecture, PlaybackError
from lerny.security import Actor, Db, deny

router = APIRouter(prefix="/api/v1/sections/{section_id}/lecture-preview")


def local_pilot() -> Pilot:
    if settings().deployment != "local":
        deny(404)
    return Pilot(settings().runtime_root / "data" / "heygen-pilot")


@router.get("")
def preview(section_id: str, session: Db, actor: Actor):
    section_student(session, actor, section_id)
    if settings().deployment != "local":
        return {"enabled": False}
    try:
        selected = LocalLecture(settings().runtime_root, section_id).status()
        if selected is not None:
            return {
                "enabled": True,
                **selected,
                "video_url": f"/api/v1/sections/{section_id}/lecture-preview/file?v={selected['media_version']}"
                if selected["status"] == "completed"
                else None,
            }
        state = local_pilot().status()
    except (PilotError, PlaybackError, OSError):
        deny(503, "샘플 강의 상태를 읽지 못했어요.")
    return {
        "enabled": True,
        **state,
        "video_url": f"/api/v1/sections/{section_id}/lecture-preview/file"
        if state["status"] == "completed"
        else None,
    }


@router.api_route("/file", methods=["GET", "HEAD"])
def video_file(section_id: str, session: Db, actor: Actor, v: str | None = None):
    section_student(session, actor, section_id)
    if settings().deployment != "local":
        deny(404)
    try:
        selected = LocalLecture(settings().runtime_root, section_id)
        binding = selected.read()
        state = selected.status(binding) if binding else None
        if state is not None:
            if state["status"] != "completed" or (v is not None and v != state["media_version"]):
                deny(404, "재생할 영상 파일을 확인해 주세요.")
            return FileResponse(
                selected.media(binding),
                media_type="video/mp4",
                filename="lerny-lecture.mp4",
                content_disposition_type="inline",
            )
        if v is not None:
            deny(404)
    except (PlaybackError, OSError):
        deny(404, "재생할 영상 파일을 확인해 주세요.")
    pilot = local_pilot()
    try:
        ready = pilot.status()["status"] == "completed"
    except PilotError:
        ready = False
    if not ready:
        deny(404, "재생할 샘플 영상이 아직 없어요.")
    return FileResponse(
        pilot.video,
        media_type="video/mp4",
        filename="lerny-stack-sample.mp4",
        content_disposition_type="inline",
    )
