"""Explicit section bindings for local test/Video Agent files. Never generates or uploads."""

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from lerny.heygen_video_agent import MAX_VIDEO_BYTES, AgentError, VideoAgentRun
from lerny.lecture_contract import Identifier, StrictModel


class PlaybackError(Exception):
    pass


class Binding(StrictModel):
    source_type: Literal["local_test_video", "video_agent"]
    title: str = Field(min_length=1, max_length=200)
    script: str = Field(default="", max_length=10000)
    asset_id: Identifier
    bytes: int = Field(ge=12, le=MAX_VIDEO_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def safe_child(root: Path, identifier: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier):
        raise PlaybackError("INVALID_LOCAL_ID")
    path = (root / identifier).resolve()
    if not path.is_relative_to(root.resolve()):
        raise PlaybackError("PATH_OUTSIDE_RUNTIME")
    return path


class LocalLecture:
    def __init__(self, runtime: Path, section_id: str):
        self.runtime = runtime
        self.root = safe_child(runtime / "data/lecture-playback", section_id)
        self.manifest = self.root / "binding.json"

    def read(self):
        if not self.manifest.exists():
            return None
        try:
            return Binding.model_validate_json(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            raise PlaybackError("INVALID_BINDING") from None

    def media(self, binding):
        base = self.runtime / "data"
        if binding.source_type == "video_agent":
            run = safe_child(base / "heygen-video-agent", binding.asset_id)
            return run / "video.mp4"
        return safe_child(self.root / "assets", binding.asset_id) / "video.mp4"

    def status(self, binding=None):
        binding = binding or self.read()
        if binding is None:
            return None
        path = self.media(binding)
        # Resolve the file too, so file symlinks cannot escape the allowed directory.
        if not path.resolve().is_relative_to(path.parent.resolve()):
            raise PlaybackError("PATH_OUTSIDE_RUNTIME")
        state = "completed"
        if binding.source_type == "video_agent":
            try:
                run = VideoAgentRun(path.parent)
                result = run.status()
            except AgentError:
                raise PlaybackError("INVALID_AGENT_STATE") from None
            state = result["status"]
            if state == "completed" and (
                result.get("sha256") != binding.sha256 or result.get("bytes") != binding.bytes
            ):
                state = "storage_missing"
        if state == "completed" and (not path.is_file() or path.stat().st_size != binding.bytes):
            state = "storage_missing"
        return {
            "status": state,
            "source_type": binding.source_type,
            "title": binding.title,
            "script": binding.script,
            "media_version": binding.sha256,
        }

    def bind(self, *, title, script="", test_video=None, run_id=None, replace=False):
        if (test_video is None) == (run_id is None):
            raise PlaybackError("SELECT_ONE_SOURCE")
        if self.manifest.exists() and not replace:
            raise PlaybackError("BINDING_EXISTS_USE_REPLACE")
        if run_id:
            source = safe_child(self.runtime / "data/heygen-video-agent", run_id) / "video.mp4"
            try:
                run_state = VideoAgentRun(source.parent).status()
            except AgentError:
                raise PlaybackError("INVALID_AGENT_STATE") from None
            if run_state["status"] != "completed":
                raise PlaybackError("VIDEO_NOT_COMPLETED")
            kind, asset_id = "video_agent", run_id
        else:
            source = Path(test_video)
            kind, asset_id = "local_test_video", uuid.uuid4().hex
        if not source.is_file() or not 12 <= source.stat().st_size <= MAX_VIDEO_BYTES:
            raise PlaybackError("INVALID_VIDEO_FILE")
        with source.open("rb") as media:
            header = media.read(12)
            if header[4:8] != b"ftyp":
                raise PlaybackError("NOT_MP4")
            media.seek(0)
            checksum = hashlib.file_digest(media, "sha256").hexdigest()
        if run_id and checksum != run_state.get("sha256"):
            raise PlaybackError("VIDEO_HASH_MISMATCH")
        binding = Binding(
            source_type=kind,
            title=title,
            script=script,
            asset_id=asset_id,
            bytes=source.stat().st_size,
            sha256=checksum,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        if test_video is not None:
            destination = self.media(binding)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        temporary = self.manifest.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(binding.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.manifest)
        return self.status()
