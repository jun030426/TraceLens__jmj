"""Local, synthetic one-video pilot. Never sends course materials to HeyGen.

Generation is an explicit CLI operation, not a student-facing or GET side effect.
The recorded provider ID allows polling/download to resume after process restarts.
"""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from lerny.environment import cloud_environment, private_env_path, read_env, runtime_root
from lerny.lecture_presentation import ASPECT_RATIO

TITLE = "스택: 마지막에 넣은 것을 먼저 꺼내요"
SCRIPT = (
    "책을 책상 위에 차곡차곡 쌓았다고 생각해 보세요. "
    "맨 마지막에 올린 책을 가장 먼저 꺼내게 되죠? "
    "스택도 같은 방식으로 동작하는 자료구조예요. "
    "나중에 들어온 데이터가 먼저 나오는 방식입니다. "
    "스택에 데이터를 넣는 연산을 푸시, 맨 위의 데이터를 꺼내는 연산을 팝이라고 해요. "
    "예를 들어, 사과를 넣고 바나나를 넣은 다음 팝을 한 번 하면 바나나가 나와요. "
    "마지막에 넣은 것을 먼저 꺼낸다. 이것이 스택의 핵심입니다."
)
MAX_VIDEO_BYTES = 100 * 1024 * 1024


class PilotError(Exception):
    """Safe, user-readable message; never include credentials/provider bodies."""


def load_credentials(path: Path | None = None) -> dict[str, str]:
    names = ("HEYGEN_API_KEY", "HEYGEN_AVATAR_ID", "HEYGEN_VOICE_ID")
    if path is None and not cloud_environment():
        path = private_env_path()
        if not path.exists() and "LERNY_ENV_FILE" not in os.environ:
            path = runtime_root() / "secrets/heygen.env"
    values = {k: v for k, v in read_env(path).items() if k in names}
    for name in names:
        if os.environ.get(name):
            values[name] = os.environ[name].strip()
    if not values.get("HEYGEN_API_KEY"):
        raise PilotError("HEYGEN_API_KEY를 로컬 비밀 설정 파일에 저장해 주세요.")
    return values


@contextmanager
def job_lock(root: Path):
    """OS lock releases on exit/crash; the lock file itself need not be deleted."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "job.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PilotError("다른 영상 작업이 실행 중입니다.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Pilot:
    def __init__(self, root: Path):
        self.root = root
        self.video = root / "sample.mp4"

    def read(self) -> dict:
        path = self.root / "job.json"
        if not path.exists():
            return {"status": "not_started"}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise TypeError
            if state.get("status") not in {
                "submitting",
                "needs_attention",
                "pending",
                "processing",
                "storing",
                "completed",
                "failed",
            }:
                raise ValueError
            return state
        except (ValueError, TypeError, OSError):
            raise PilotError("영상 작업 기록을 읽을 수 없습니다. 기록을 확인해 주세요.") from None

    def save(self, state: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(UTC).isoformat()
        temporary = self.root / "job.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.root / "job.json")

    def status(self) -> dict:
        state = self.read()
        status = state["status"]
        if status == "completed" and not self.video.is_file():
            status = "storage_missing"
        return {
            "status": status,
            "title": TITLE,
            "script": SCRIPT,
            "source_type": "manually_written_demo",
            "updated_at": state.get("updated_at"),
        }

    def start(self, client: httpx.Client, avatar: str, voice: str) -> dict:
        if not avatar or not voice:
            raise PilotError("HEYGEN_AVATAR_ID와 HEYGEN_VOICE_ID를 선택해 주세요.")
        payload = {
            "type": "avatar",
            "avatar_id": avatar,
            "voice_id": voice,
            "script": SCRIPT,
            "title": TITLE,
            "resolution": "1080p",
            "aspect_ratio": ASPECT_RATIO,
        }
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        state = self.read()
        if state["status"] != "not_started":
            if state.get("fingerprint") != fingerprint:
                raise PilotError("기존 샘플과 설정이 다릅니다. 기존 작업을 먼저 확인해 주세요.")
            if not state.get("video_id"):
                raise PilotError(
                    "이전 요청의 접수 여부를 HeyGen에서 확인해 주세요. 재생성하지 않았습니다."
                )
            if state["status"] == "failed":
                raise PilotError(
                    "기존 영상 생성이 실패했습니다. 원인 확인 후 새 작업이 필요합니다."
                )
            return state
        # Persist BEFORE the chargeable call. A crash/timeout must never auto-submit twice.
        state = {"status": "submitting", "fingerprint": fingerprint, "request": payload}
        self.save(state)
        try:
            response = client.post("/v3/videos", json=payload)
            response.raise_for_status()
            video_id = response.json()["data"]["video_id"]
            if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", video_id):
                raise ValueError
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            state["status"] = "needs_attention"
            self.save(state)
            raise PilotError(
                "생성 접수를 확인하지 못했습니다. HeyGen 기록을 확인해 주세요."
            ) from None
        state.update(status="pending", video_id=video_id)
        self.save(state)
        return state

    def attach_video(self, video_id: str):
        """Explicit recovery after an ambiguous submission, never creates another video."""
        state = self.read()
        if state["status"] not in {"submitting", "needs_attention"} or state.get("video_id"):
            raise PilotError("접수 결과가 불명확한 작업에만 영상 ID를 연결할 수 있습니다.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", video_id):
            raise PilotError("영상 ID 형식을 확인해 주세요.")
        state.update(status="pending", video_id=video_id)
        self.save(state)

    def poll(self, client: httpx.Client, media: httpx.Client) -> str:
        state = self.read()
        if state["status"] == "completed" and self.video.is_file():
            return "completed"
        if not state.get("video_id"):
            raise PilotError("조회할 영상 ID가 없습니다. 생성 요청 상태를 먼저 확인해 주세요.")
        if state["status"] == "failed":
            raise PilotError("HeyGen 영상 생성이 실패했습니다. HeyGen에서 원인을 확인해 주세요.")
        try:
            response = client.get("/v3/videos/" + quote(state["video_id"], safe=""))
            response.raise_for_status()
            result = response.json()["data"]
            status = result["status"]
            if status not in {"pending", "processing", "completed", "failed"}:
                raise ValueError
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise PilotError(
                "상태 조회에 실패했습니다. resume으로 이어서 확인할 수 있습니다."
            ) from None
        if status == "completed":
            state["status"] = "storing"
            self.save(state)
            self.download(media, result.get("video_url", ""))
        state["status"] = status
        self.save(state)
        if status == "failed":
            raise PilotError("HeyGen 영상 생성이 실패했습니다. HeyGen에서 원인을 확인해 주세요.")
        return status

    def download(self, media: httpx.Client, url: str):
        part = self.root / "sample.mp4.part"
        try:
            # No API credentials on media requests. Check each redirect before following it.
            for _ in range(5):
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
                    raise PilotError(
                        "영상 다운로드 주소를 확인해 주세요. 외부 주소는 자동으로 열지 않습니다."
                    )
                with media.stream("GET", url, follow_redirects=False) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    total = 0
                    with part.open("wb") as output:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > MAX_VIDEO_BYTES:
                                raise PilotError("샘플 영상이 100MB 제한을 초과했습니다.")
                            output.write(chunk)
                    with part.open("rb") as check:
                        header = check.read(12)
                    if len(header) < 12 or header[4:8] != b"ftyp":
                        raise PilotError("완성된 파일이 MP4 형식이 아닙니다.")
                    part.replace(self.video)
                    return
            raise PilotError("영상 다운로드 이동 횟수를 초과했습니다.")
        except (httpx.HTTPError, ValueError, KeyError, OSError):
            raise PilotError(
                "영상 저장에 실패했습니다. resume으로 저장을 다시 시도할 수 있습니다."
            ) from None
        finally:
            part.unlink(missing_ok=True)
