"""Dedicated Linux worker. The configured sandbox command owns container cleanup."""
import json
import os
import time
from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import CodeRun, CodeWorker, now, uid
from lerny.tracing.service import run_in_sandbox


def touch(worker_id, ready=True):
    with Session(engine()) as session:
        session.execute(insert(CodeWorker).values(id=worker_id, last_seen_at=now(), ready=ready)
            .on_conflict_do_update(index_elements=[CodeWorker.id],
                                  set_={"last_seen_at": now(), "ready": ready}))
        session.execute(delete(CodeRun).where(CodeRun.expires_at < now()))
        session.execute(delete(CodeWorker).where(CodeWorker.last_seen_at < now() - timedelta(days=1)))
        session.commit()


def run_once():
    with Session(engine()) as session:
        from lerny.operations import state, enabled, touch as ops_touch
        control = state(session, lock=True)
        ops_touch(session, "code")
        if not enabled(control, "grading"):
            session.commit()
            return False
        item = session.scalar(select(CodeRun).where(
            or_(CodeRun.status == "queued", (CodeRun.status == "running") & (CodeRun.lease_until < now())),
            CodeRun.expires_at > now(),
        ).order_by(CodeRun.created_at).with_for_update(skip_locked=True).limit(1))
        if item is None:
            session.commit()
            return False
        item.status, item.lease_token = "running", uid()
        item.lease_until = now() + timedelta(seconds=60)
        run_id, token, language, source = item.id, item.lease_token, item.language, item.source
        ops_touch(session, "code", busy=True)
        session.commit()
    result, error = None, None
    try:
        if language not in {"python", "java", "c"}:
            raise ValueError("Unsupported runtime")
        result = run_in_sandbox(language, source)
        if len(json.dumps(result).encode()) > 6 * 1024 * 1024:
            raise ValueError("Result too large")
    except Exception:
        # Neither submitted source nor debugger/credential-bearing errors enter logs.
        error = "SANDBOX_FAILED"
    with Session(engine()) as session:
        item = session.scalar(select(CodeRun).where(CodeRun.id == run_id).with_for_update())
        if item and item.lease_token == token and item.expires_at > now():
            item.source = ""
            item.result, item.error_code = result, error
            item.status = "failed" if error else "succeeded"
            item.lease_token, item.lease_until = None, None
            session.commit()
    from lerny.operations import finished
    finished("code")
    return True


def main():
    if not settings().dedicated_worker or not settings().trace_sandbox_command:
        raise SystemExit("A dedicated worker with an isolated sandbox is required")
    worker_id = os.environ.get("LERNY_CODE_WORKER_ID", "aws-linux-1")
    while True:
        try:
            touch(worker_id)
            if not run_once():
                time.sleep(1)
        except Exception:
            print("Code worker temporarily unavailable", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
