"""Compile an ordered set of reusable slide assets and narration into one Studio video."""

from typing import Annotated, Literal

from pydantic import Field

from lerny.heygen_lecture_profile import LERNY_LOOK_ID, LERNY_VOICE_ID
from lerny.lecture_contract import StrictModel

AssetId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,150}$")]
Script = Annotated[str, Field(min_length=1, max_length=5000, pattern=r"\S")]


class AvatarVEngine(StrictModel):
    type: Literal["avatar_v"] = "avatar_v"
    # Optional defaults preserve historical request fingerprints on reload.
    more_blinking: Literal[False] | None = None


class AssetSource(StrictModel):
    type: Literal["asset_id"] = "asset_id"
    asset_id: AssetId


class SlideBackground(StrictModel):
    type: Literal["image"] = "image"
    source: AssetSource


class SlideAvatar(StrictModel):
    type: Literal["avatar"] = "avatar"
    avatar_id: AssetId = LERNY_LOOK_ID
    voice_id: AssetId = LERNY_VOICE_ID
    script: Script
    # Omit an engine when reloading historical requests so their fingerprints survive.
    engine: AvatarVEngine | None = None
    motion_prompt: str | None = None
    expressiveness: Literal["low", "medium", "high"] | None = None
    remove_background: Literal[True] = True
    background: SlideBackground


class StudioScene(StrictModel):
    type: Literal["avatar_video"] = "avatar_video"
    input: SlideAvatar


class StudioCaption(StrictModel):
    file_format: Literal["srt"] = "srt"
    style: Literal["default"] = "default"


class StudioRequest(StrictModel):
    type: Literal["studio"] = "studio"
    title: Annotated[str, Field(min_length=1, max_length=200)]
    aspect_ratio: Literal["16:9"] = "16:9"
    resolution: Literal["1080p"] = "1080p"
    caption: StudioCaption | None = None
    scenes: Annotated[list[StudioScene], Field(min_length=1, max_length=50)]


def compile_studio(title, asset_ids, scripts):
    scenes = [
        StudioScene(
            input=SlideAvatar(
                script=script,
                engine=AvatarVEngine(more_blinking=False),
                background=SlideBackground(source=AssetSource(asset_id=asset_id)),
            )
        )
        for asset_id, script in zip(asset_ids, scripts, strict=True)
    ]
    return StudioRequest(title=title, caption=StudioCaption(), scenes=scenes).model_dump(exclude_none=True)
