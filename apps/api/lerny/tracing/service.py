"""API side of the learning trace: hands source to the sandbox and validates what comes back.

Nothing here executes student code. Without a configured, verified sandbox (docs/06 격리와 초기
자원 제한) the endpoint answers 503 instead of falling back to the host.
"""

import json
import subprocess
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from lerny.config import settings
from lerny.models import Section
from lerny.security import Actor, Db, course_access, deny

router = APIRouter(prefix="/api/v1")

LANGUAGES = {"python": "python", "java": "java", "c": "c"}
MAX_ENVELOPE_BYTES = 6 * 1024 * 1024
SANDBOX_TIMEOUT = 45
# 실행 병렬수: 워커 전체 2개부터 측정 (docs/06)
slots = threading.BoundedSemaphore(2)


class TraceInput(BaseModel):
    # no whitespace stripping: trimming a leading blank line would shift every line number
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=32 * 1024)


def sandbox_ready() -> bool:
    if getattr(settings(), "trace_backend", "disabled") == "queue":
        from lerny.tracing.queue import worker_ready
        return worker_ready()
    return bool(settings().trace_sandbox_command)


def run_in_sandbox(language: str, source: str) -> dict:
    command = settings().trace_sandbox_command
    if not command:
        raise HTTPException(503, detail="격리 실행 환경이 아직 준비되지 않아 실행 흐름을 볼 수 없어요.")
    if not slots.acquire(timeout=10):
        raise HTTPException(429, detail="다른 실행이 끝나면 다시 시도해 주세요.")
    try:
        proc = subprocess.run(
            [*command, "python", "-m", "lerny.tracing.runner", "--language", language],
            input=source.encode("utf-8"),
            capture_output=True,
            timeout=SANDBOX_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, detail="실행 흐름을 만드는 데 시간이 너무 오래 걸렸어요.")
    finally:
        slots.release()
    if proc.returncode != 0 or len(proc.stdout) > MAX_ENVELOPE_BYTES:
        raise HTTPException(502, detail="실행 환경에서 기록을 받지 못했어요.")
    try:
        envelope = json.loads(proc.stdout)
    except ValueError:
        raise HTTPException(502, detail="실행 환경에서 기록을 받지 못했어요.")
    if envelope.get("language") != language or not isinstance(envelope.get("events"), list):
        raise HTTPException(502, detail="실행 환경에서 기록을 받지 못했어요.")
    return envelope


@router.post("/sections/{section_id}/practice/trace")
def practice_trace(section_id: str, body: TraceInput, session: Db, actor: Actor):
    """Learning-only visualization run. Not a submission and never graded (docs/06)."""
    section = session.get(Section, section_id)
    if not section:
        deny(404, "분반을 찾을 수 없습니다.")
    course = course_access(session, actor, section.course_id)
    # the course decides the language; the client cannot pick another runtime
    language = LANGUAGES.get(course.teaching_language.lower())
    if not language:
        deny(422, "이 수업 언어는 실행 흐름 보기를 지원하지 않아요.")
    if settings().trace_backend == "queue":
        from lerny.tracing.queue import submit_and_wait
        return submit_and_wait(session, actor, section, language, body.source)
    return run_in_sandbox(language, body.source)
