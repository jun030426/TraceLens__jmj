"""Local lecture cards -> explicit Avatar V Studio request. No generative API calls.

This is an internal preparation plan, not a payload for /v3/video-agents.
Only the durable video worker uploads the cards and submits /v3/videos.
"""

import hashlib
import io
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from lerny.heygen_lecture_profile import LERNY_LOOK_ID, LERNY_VOICE_ID, NarrationLesson
from lerny.heygen_slides import StudioRequest, compile_studio
from lerny.lecture_contract import StrictModel

PROFILE_ID = "lerny_avatar_v_1080p_v1"
BACKGROUND = Path(__file__).with_name("assets") / "lecture-ivory.png"
MOTION_DIRECTION = (
    "Keep the reference photo's relaxed neutral expression, forward gaze and head pose. "
    "Minimize head turns, nodding, tilting, eyebrow raises and facial expression changes. "
    "Use only small speech-synchronized lip movements and occasional natural blinks. "
    "Keep the seated pose and hands still; no exaggerated smiles or large gestures."
)


class SiteVideoPlan(StrictModel):
    type: Literal["lerny_studio_plan"] = "lerny_studio_plan"
    profile: Literal["lerny_avatar_v_1080p_v1"] = PROFILE_ID
    lesson: NarrationLesson


def presentation_settings():
    return {
        "profile": PROFILE_ID,
        "endpoint": "/v3/videos",
        "engine": "avatar_v",
        "resolution": "1080p",
        "aspect_ratio": "16:9",
        "avatar_id": LERNY_LOOK_ID,
        "voice_id": LERNY_VOICE_ID,
        "more_blinking": False,
        "motion_direction": MOTION_DIRECTION,
        "motion_control": "photo_without_eligible_reference",
        "motion_prompt_applied": False,
        "motion_note": "현재 사진 아바타의 Avatar V 직접 생성은 세부 모션 지시를 지원하지 않습니다.",
    }


def compile_site_plan(data):
    plan = SiteVideoPlan(lesson=NarrationLesson.model_validate(data))
    scene_scripts(plan.lesson)  # Reject oversized content before queueing/uploading.
    return plan.model_dump()


def scene_scripts(lesson):
    # Preserve every character and its order; do not ask an agent to rewrite narration.
    scripts = []
    for paragraph in lesson.narration:
        while len(paragraph) > 180:
            boundary = max(paragraph.rfind(". ", 40, 180) + 1,
                           paragraph.rfind("。", 40, 180) + 1)
            if boundary <= 1:
                boundary = paragraph.rfind(" ", 40, 180)
            if boundary <= 0:
                boundary = 180
            scripts.append(paragraph[:boundary])
            paragraph = paragraph[boundary:]
        if paragraph.strip():
            scripts.append(paragraph)
        elif scripts:
            scripts[-1] += paragraph
    if not 1 <= len(scripts) <= 50:
        raise ValueError("VIDEO_TOO_MANY_SCENES")
    return scripts


def font_path():
    candidates = [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/malgun.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError("VIDEO_KOREAN_FONT_UNAVAILABLE")


def wrapped(text, font, width):
    lines, line = [], ""
    for char in text:
        if char == "\n":
            lines.append(line)
            line = ""
        elif line and font.getlength(line + char) > width:
            lines.append(line)
            line = char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def card_image(title, script, position, total):
    """Fixed original background; literal validated narration in the right material area."""
    with Image.open(BACKGROUND) as original:
        if original.size != (1920, 1080):
            raise ValueError("VIDEO_BACKGROUND_SIZE_INVALID")
        canvas = original.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    face = str(font_path())
    title_font, body_font, small_font = [ImageFont.truetype(face, n) for n in (48, 42, 27)]
    headings = wrapped(title, title_font, 920)
    lines = wrapped(script.strip(), body_font, 920)
    if len(headings) > 3 or len(lines) > 9:
        raise ValueError("VIDEO_CARD_TEXT_OVERFLOW")
    # Preserve the left-hand seated lecturer area and the bottom caption safe area.
    draw.rounded_rectangle((790, 100, 1840, 880), radius=28, fill="#FAF8F2")
    draw.text((845, 128), f"LERNY  ·  {position}/{total}", font=small_font, fill="#365A48")
    y = 190
    for line in headings:
        draw.text((845, y), line, font=title_font, fill="#283A32")
        y += 62
    y += 24
    if y + len(lines) * 56 > 855:
        raise ValueError("VIDEO_CARD_TEXT_OVERFLOW")
    for line in lines:
        draw.text((845, y), line, font=body_font, fill="#353535")
        y += 56
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


def prepare_request(data, client):
    plan = SiteVideoPlan.model_validate(data)
    scripts = scene_scripts(plan.lesson)
    # Render/validate every card before any upload; never silently clip teaching content.
    images = [card_image(plan.lesson.title, text, i, len(scripts))
              for i, text in enumerate(scripts, 1)]
    assets, reused = [], {}
    for picture in images:
        fingerprint = hashlib.sha256(picture).hexdigest()
        if fingerprint not in reused:
            response = client.post("https://api.heygen.com/v3/assets", files={
                "file": (f"lecture-{fingerprint[:16]}.png", picture, "image/png")})
            response.raise_for_status()
            from pydantic import TypeAdapter

            from lerny.heygen_slides import AssetId
            reused[fingerprint] = TypeAdapter(AssetId).validate_python(
                response.json()["data"]["asset_id"])
        assets.append(reused[fingerprint])
    return compile_studio(plan.lesson.title, assets, scripts)


def checked_request(data):
    """Never silently fall back to Video Agent, another avatar, voice or engine."""
    body = StudioRequest.model_validate(data).model_dump(exclude_none=True)
    for scene in body["scenes"]:
        avatar = scene["input"]
        if (avatar["avatar_id"] != LERNY_LOOK_ID or avatar["voice_id"] != LERNY_VOICE_ID
                or avatar.get("engine") != {"type": "avatar_v", "more_blinking": False}
                or "motion_prompt" in avatar or "expressiveness" in avatar):
            raise ValueError("VIDEO_PROFILE_REVIEW_REQUIRED")
    return body
