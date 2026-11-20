"""Authenticated API-to-Linux queue. No student code executes in an API process."""
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lerny.db import engine
from lerny.models import CodeRun, CodeWorker, now
from lerny.security import course_access

WAIT_SECONDS = 90


def worker_ready():
    try:
        with Session(engine()) as session:
            return session.scalar(select(CodeWorker.id).where(
                CodeWorker.ready.is_(True),
                CodeWorker.last_seen_at > now() - timedelta(seconds=90),
            ).limit(1)) is not None
    except SQLAlchemyError:
        return False


def submit_and_wait(session, actor, section, language, source):
    if not worker_ready():
        raise HTTPException(503, "코드 실행 서버가 준비 중입니다. 잠시 후 다시 시도해 주세요.")
    if len(source.encode("utf-8")) > 32 * 1024:
        raise HTTPException(413, "코드는 UTF-8 기준 32KB 이내로 입력해 주세요.")
    # One brief cross-instance lock makes the global and per-account limits exact.
    session.execute(text("SELECT pg_advisory_xact_lock(1421338317)"))
    active = [CodeRun.status.in_(["queued", "running"]), CodeRun.expires_at > now()]
    if session.scalar(select(func.count()).select_from(CodeRun).where(*active, CodeRun.owner_id == actor.id)):
        raise HTTPException(429, "진행 중인 코드 실행이 끝난 뒤 다시 시도해 주세요.")
    if session.scalar(select(func.count()).select_from(CodeRun).where(*active)) >= 5:
        raise HTTPException(429, "실행 요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    run = CodeRun(owner_id=actor.id, section_id=section.id, language=language, source=source,
                  expires_at=now() + timedelta(seconds=WAIT_SECONDS))
    session.add(run)
    session.flush()
    run_id, course_id, actor_id = run.id, section.course_id, actor.id
    session.expunge(actor)
    session.commit()
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        # Release the pooled DB connection between polls.
        with Session(engine()) as polling:
            current = polling.get(CodeRun, run_id)
            if not current or current.owner_id != actor_id:
                raise HTTPException(504, "코드 실행 요청이 만료되었습니다.")
            if current.status == "succeeded":
                course_access(polling, actor, course_id)
                result = current.result
                polling.delete(current)
                polling.commit()
                return result
            if current.status == "failed":
                polling.delete(current)
                polling.commit()
                raise HTTPException(502, "실행 환경에서 기록을 받지 못했습니다. 코드를 확인하고 다시 시도해 주세요.")
    with Session(engine()) as cleanup:
        cleanup.execute(delete(CodeRun).where(CodeRun.id == run_id, CodeRun.owner_id == actor_id))
        cleanup.commit()
    raise HTTPException(504, "실행 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
