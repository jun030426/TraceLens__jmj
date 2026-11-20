"""Explicit, resumable local Video Agent execution. No network on import/status.

The offline compiler remains independent. This runner never publishes to students.
One directory represents one submission; an ambiguous POST is never retried.
"""

import hashlib
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, urlparse

import httpx
from pydantic import Field, ValidationError

from lerny.heygen_pilot import job_lock
from lerny.heygen_request_preview import ENDPOINT, MAX_PROMPT_CHARACTERS, ProviderId
from lerny.heygen_slides import StudioRequest
from lerny.lecture_contract import StrictModel

API_ROOT = "https://api.heygen.com"
MAX_VIDEO_BYTES = 100 * 1024 * 1024
RemoteId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,150}$")]


class AgentError(Exception):
    """Only local error codes; never include response bodies, signed URLs or keys."""


class AgentRequest(StrictModel):
    mode: Literal["generate"]
    orientation: Literal["landscape"]
    avatar_id: ProviderId
    voice_id: ProviderId
    visibility: Literal["private"] = "private"
    style_id: ProviderId | None = None
    prompt: Annotated[
        str, Field(min_length=1, max_length=MAX_PROMPT_CHARACTERS, pattern=r"\S")
    ]


class RunState(StrictModel):
    kind: Literal["agent", "studio"] = "agent"
    status: Literal[
        "submitting",
        "needs_attention",
        "pending",
        "processing",
        "storing",
        "completed",
        "failed",
        "cancelled",
    ]
    fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    session_id: RemoteId | None = None
    video_id: RemoteId | None = None
    error_code: str | None = None
    retry_after_seconds: float = 30.0
    bytes: int | None = None
    sha256: str | None = None
    updated_at: str | None = None


def retry_delay(response):
    value = response.headers.get("retry-after", "30")
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 30
    return max(30.0, seconds) if seconds < float("inf") else 30.0


class VideoAgentRun:
    def __init__(self, root: Path):
        self.root = root
        self.video = root / "video.mp4"
        self.state_file = root / "video-agent-job.json"

    def read(self):
        if not self.state_file.exists():
            return None
        try:
            return RunState.model_validate_json(
                self.state_file.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            raise AgentError("STATE_UNREADABLE") from None

    def save(self, state):
        state.updated_at = datetime.now(UTC).isoformat()
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.state_file)

    def status(self):
        state = self.read()
        result = state.model_dump() if state else {"status": "not_started"}
        if (
            state
            and state.status == "completed"
            and (not self.video.is_file() or self.video.stat().st_size != state.bytes)
        ):
            result["status"] = "storage_missing"
        return {**result, "publication_allowed": False}

    def start(self, client, body, *, confirmed=False):
        if confirmed is not True:
            raise AgentError("EXPLICIT_GENERATION_CONFIRMATION_REQUIRED")
        try:
            studio = isinstance(body, dict) and body.get("type") == "studio"
            schema = StudioRequest if studio else AgentRequest
            payload = schema.model_validate(body).model_dump(exclude_none=True)
        except ValidationError:
            raise AgentError("INVALID_AGENT_REQUEST") from None
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        with job_lock(self.root):
            existing = self.read()
            if existing:
                if existing.fingerprint != fingerprint:
                    raise AgentError("REQUEST_CHANGED")
                if not (existing.video_id if studio else existing.session_id):
                    raise AgentError("SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT")
                return self.status()
            state = RunState(status="submitting", fingerprint=fingerprint, kind="studio" if studio else "agent")
            # Persist BEFORE the billable POST, including before a possible process crash.
            self.save(state)
            try:
                endpoint = API_ROOT + "/v3/videos" if studio else ENDPOINT
                response = client.post(endpoint, json=payload, follow_redirects=False)
                response.raise_for_status()
                data = response.json()["data"]
                accepted = RunState(
                    status="pending",
                    fingerprint=fingerprint,
                    kind=state.kind,
                    session_id=None if studio else data["session_id"],
                    video_id=data["video_id"] if studio else data.get("video_id"),
                )
                if not (accepted.video_id if studio else accepted.session_id):
                    raise ValueError
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                state.status = "needs_attention"
                state.error_code = "SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT"
                self.save(state)
                raise AgentError(state.error_code) from None
            self.save(accepted)
            return self.status()

    def attach_session(self, session_id):
        return self._recover("agent", "session_id", session_id)

    def attach_video(self, video_id):
        return self._recover("studio", "video_id", video_id)

    def _recover(self, kind, field, identifier):
        """Operator recovery after checking the provider's receipt. Never creates a session."""
        with job_lock(self.root):
            state = self.read()
            if (
                not state
                or state.kind != kind
                or getattr(state, field)
                or state.status not in {"submitting", "needs_attention"}
            ):
                raise AgentError("RECOVERY_NOT_ALLOWED")
            try:
                updated = RunState.model_validate(
                    {
                        **state.model_dump(),
                        field: identifier,
                        "status": "pending",
                        "error_code": None,
                    }
                )
                if not getattr(updated, field):
                    raise ValueError
            except ValueError:
                raise AgentError("INVALID_" + field.upper()) from None
            self.save(updated)
        return self.status()

    def _get(self, client, path, state):
        try:
            response = client.get(API_ROOT + path, follow_redirects=False)
            state.retry_after_seconds = retry_delay(response)
            if response.status_code == 429 or response.status_code >= 500:
                state.error_code = "STATUS_RETRYABLE"
                self.save(state)
                return None
            response.raise_for_status()
            data = response.json()["data"]
            if not isinstance(data, dict):
                raise TypeError
            return data
        except httpx.TransportError:
            state.error_code = "STATUS_RETRYABLE"
            self.save(state)
            return None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AgentError("STATUS_LOOKUP_FAILED") from None

    def _poll_agent_session(self, client, state):
        session = self._get(
            client, "/v3/video-agents/" + quote(state.session_id, safe=""), state
        )
        if session is None:
            return False
        if session.get("session_id") != state.session_id:
            raise AgentError("SESSION_ID_MISMATCH")
        session_status = session.get("status")
        if session_status in {"failed", "cancelled", "canceled", "stopped"}:
            state.status = "failed" if session_status == "failed" else "cancelled"
            state.error_code = "PROVIDER_TERMINAL_FAILURE"
            self.save(state)
            return False
        if session_status not in {"thinking", "generating", "completed"}:
            state.status = "needs_attention"
            state.error_code = "SESSION_REQUIRES_REVIEW"
            self.save(state)
            return False
        video_id = session.get("video_id") or state.video_id
        if video_id:
            try:
                RunState.model_validate(
                    {**state.model_dump(), "video_id": video_id}
                )
            except ValidationError:
                raise AgentError("INVALID_VIDEO_ID") from None
            if state.video_id and video_id != state.video_id:
                raise AgentError("VIDEO_ID_CHANGED")
            state.video_id = video_id
        state.status = "processing"
        if session_status == "completed" and not state.video_id:
            state.status = "needs_attention"
            state.error_code = "COMPLETED_SESSION_WITHOUT_VIDEO"
        self.save(state)
        return bool(state.video_id)

    def poll(self, client, media):
        """One bounded poll/download attempt. Caller schedules another after retry_after_seconds."""
        with job_lock(self.root):
            state = self.read()
            if not state or not (state.video_id if state.kind == "studio" else state.session_id):
                raise AgentError("NO_SESSION_ID")
            if state.status in {"failed", "cancelled"}:
                return self.status()
            if self.status()["status"] == "completed":
                return self.status()
            state.error_code = None
            if state.kind == "agent" and not self._poll_agent_session(client, state):
                return self.status()
            video = self._get(
                client, "/v3/videos/" + quote(state.video_id, safe=""), state
            )
            if video is None:
                return self.status()
            if video.get("id", state.video_id) != state.video_id:
                raise AgentError("VIDEO_ID_MISMATCH")
            status = video.get("status")
            if status in {"failed", "cancelled", "canceled"}:
                state.status = "failed" if status == "failed" else "cancelled"
                state.error_code = "PROVIDER_TERMINAL_FAILURE"
            elif status in {"pending", "processing"}:
                state.status = "processing"
            elif status == "completed":
                state.status = "storing"
                self.save(state)
                try:
                    size, sha256 = self._download(media, video.get("video_url"))
                except AgentError:
                    state.error_code = "DOWNLOAD_RETRYABLE"
                    self.save(state)
                    raise
                state.status, state.bytes, state.sha256 = "completed", size, sha256
            else:
                state.status = "needs_attention"
                state.error_code = "UNKNOWN_VIDEO_STATUS"
            self.save(state)
            return self.status()

    def _download(self, media, url):
        part = self.root / "video.mp4.part"
        try:
            for _ in range(5):
                if not isinstance(url, str):
                    raise AgentError("INVALID_MEDIA_URL")
                parsed = urlparse(url)
                host = parsed.hostname or ""
                if (
                    parsed.scheme != "https"
                    or parsed.username
                    or parsed.password
                    or parsed.port not in {None, 443}
                    or not any(
                        host == d or host.endswith("." + d)
                        for d in ("heygen.ai", "heygen.com", "heygen.io")
                    )
                ):
                    raise AgentError("INVALID_MEDIA_URL")
                # Explicit Request avoids client default API headers/cookies; auth=None disables auth.
                request = httpx.Request("GET", url, headers={"Accept": "video/mp4"})
                response = media.send(
                    request, stream=True, auth=None, follow_redirects=False
                )
                try:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    expected = int(length) if length is not None else None
                    if expected is not None and not 12 <= expected <= MAX_VIDEO_BYTES:
                        raise AgentError("INVALID_MEDIA_SIZE")
                    total, fingerprint = 0, hashlib.sha256()
                    with part.open("wb") as output:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > MAX_VIDEO_BYTES:
                                raise AgentError("MEDIA_TOO_LARGE")
                            fingerprint.update(chunk)
                            output.write(chunk)
                    if expected is not None and total != expected:
                        raise AgentError("INCOMPLETE_MEDIA")
                    with part.open("rb") as check:
                        header = check.read(12)
                    # Container signature only; playback/content quality require later review.
                    if len(header) < 12 or header[4:8] != b"ftyp":
                        raise AgentError("NOT_MP4")
                    part.replace(self.video)
                    return total, fingerprint.hexdigest()
                finally:
                    response.close()
            raise AgentError("TOO_MANY_MEDIA_REDIRECTS")
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, OSError):
            raise AgentError("MEDIA_SAVE_FAILED") from None
        finally:
            part.unlink(missing_ok=True)
