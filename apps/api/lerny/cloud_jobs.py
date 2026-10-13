"""Authenticated cloud scheduler and an inference-only worker protocol."""

import json
import math
import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from pydantic import Field
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from lerny.auth import Input
from lerny.config import settings
from lerny.db import engine
from lerny.models import AIWorker, Job, ModelCall, UploadIntent, now, uid
from lerny.security import Db, deny

router = APIRouter(prefix="/api/internal")


def cleanup():
    from lerny import storage
    with Session(engine()) as session:
        expired = list(session.scalars(select(UploadIntent).where(
            UploadIntent.expires_at < now()).with_for_update(skip_locked=True).limit(3)))
        for intent in expired:
            try:
                storage.delete_object(intent.object_key)
            except storage.StorageUnavailable:
                continue
            session.delete(intent)
        terminal = select(Job.id).where(Job.status.in_(["succeeded", "failed", "cancelled"]))
        session.execute(delete(ModelCall).where(ModelCall.job_id.in_(terminal),
            ModelCall.created_at < now() - timedelta(days=1)))
        session.execute(delete(AIWorker).where(AIWorker.last_seen_at < now() - timedelta(days=1)))
        session.commit()


def worker_auth(authorization: str | None = Header(default=None)):
    secret = settings().ai_worker_token.get_secret_value()
    if not secret or not secrets.compare_digest(authorization or "", "Bearer " + secret):
        deny(401, "실행기 인증이 필요합니다.")


def scheduler_auth(authorization: str | None = Header(default=None)):
    secret = settings().cron_secret.get_secret_value()
    if not secret or not secrets.compare_digest(authorization or "", "Bearer " + secret):
        deny(401, "작업 처리 인증이 필요합니다.")


@router.post("/jobs/tick", dependencies=[Depends(scheduler_auth)])
def tick():
    if settings().deployment != "cloud":
        deny(409)
    from lerny.worker import run_once

    cleanup()

    started, processed = time.monotonic(), 0
    # Each invocation is bounded. No permanent worker or request waiting for GPU inference.
    while processed < 4 and time.monotonic() - started < 120:
        if not run_once():
            break
        processed += 1
    return {"processed": processed}


class WorkerInput(Input):
    worker_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    models_ready: bool = True


def touch_worker(session, body):
    session.execute(
        insert(AIWorker)
        .values(id=body.worker_id, last_seen_at=now(), models_ready=body.models_ready)
        .on_conflict_do_update(
            index_elements=[AIWorker.id],
            set_={"last_seen_at": now(), "models_ready": body.models_ready},
        )
    )


def ai_status(session):
    online = session.scalar(
        select(AIWorker.id)
        .where(
            AIWorker.last_seen_at > now() - timedelta(seconds=90), AIWorker.models_ready.is_(True)
        )
        .limit(1)
    )
    return "online" if online else "offline"


@router.post("/ai/claim", dependencies=[Depends(worker_auth)])
def claim(body: WorkerInput, session: Db):
    touch_worker(session, body)
    if not body.models_ready:
        session.commit()
        return {"task": None}
    call = session.scalar(
        select(ModelCall)
        .join(Job, ModelCall.job_id == Job.id)
        .where(
            Job.status.in_(["waiting_ai", "queued", "running"]),
            or_(
                ModelCall.status == "queued",
                (ModelCall.status == "running") & (ModelCall.lease_until < now()),
            ),
        )
        .order_by(ModelCall.created_at, ModelCall.id)
        .with_for_update(of=ModelCall, skip_locked=True)
        .limit(1)
    )
    if not call:
        session.commit()
        return {"task": None}
    job = session.get(Job, call.job_id)
    if call.generation != job.payload.get("_ai_generation", 0):
        call.status = "cancelled"
        session.commit()
        return {"task": None}
    call.status, call.lease_token = "running", uid()
    call.lease_until = now() + timedelta(seconds=180)
    session.commit()
    return {"task": {"id": call.id, "lease_token": call.lease_token, **call.request}}


class LeaseInput(WorkerInput):
    lease_token: str = Field(min_length=36, max_length=36)


def leased_call(session, call_id, body, allow_completed=False):
    call = session.scalar(select(ModelCall).where(ModelCall.id == call_id).with_for_update())
    if not call or not secrets.compare_digest(call.lease_token or "", body.lease_token):
        deny(409, "작업 실행 권한이 만료되었습니다.")
    job = session.get(Job, call.job_id)
    if allow_completed and call.status in {"succeeded", "failed"} and (
        call.generation == job.payload.get("_ai_generation", 0)
    ):
        return call, job
    if job.status not in {"waiting_ai", "queued", "running"} or (
        call.generation != job.payload.get("_ai_generation", 0)
    ):
        deny(409, "취소되었거나 교체된 작업입니다.")
    return call, job


@router.post("/ai/tasks/{call_id}/heartbeat", dependencies=[Depends(worker_auth)])
def heartbeat(call_id: str, body: LeaseInput, session: Db):
    call, _ = leased_call(session, call_id, body)
    if call.status != "running" or call.lease_until < now():
        deny(409, "작업 실행 시간이 만료되었습니다.")
    touch_worker(session, body)
    call.lease_until = now() + timedelta(seconds=180)
    session.commit()
    return {"status": "ok"}


class ResultInput(LeaseInput):
    response: dict | None = None
    error: bool = False


def validate_response(call, response):
    try:
        size = len(json.dumps(response, allow_nan=False).encode())
    except (ValueError, TypeError):
        deny(422, "모델 응답 형식을 확인해 주세요.")
    if not response or size > 3 * 1024 * 1024:
        deny(422, "모델 응답 크기·형식을 확인해 주세요.")
    if call.request["operation"] == "embed":
        vectors = response.get("embeddings")
        expected = len(call.request["body"]["input"])
        if (
            not isinstance(vectors, list)
            or len(vectors) != expected
            or any(
                not isinstance(v, list)
                or not 1 <= len(v) <= 8192
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in v)
                for v in vectors
            )
            or len({len(v) for v in vectors}) != 1
        ):
            deny(422, "임베딩 응답을 확인해 주세요.")
        return {"embeddings": vectors}
    message = response.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        deny(422, "모델 응답을 확인해 주세요.")
    try:
        json.loads(message["content"])
    except (ValueError, TypeError):
        deny(422, "모델 JSON 응답을 확인해 주세요.")
    return {"message": {"content": message["content"]}}


@router.post("/ai/tasks/{call_id}/result", dependencies=[Depends(worker_auth)])
def result(call_id: str, body: ResultInput, session: Db):
    call, job = leased_call(session, call_id, body, allow_completed=True)
    if call.status in {"succeeded", "failed"}:
        return {"status": call.status}
    if call.status != "running" or call.lease_until < now():
        deny(409, "작업 실행 시간이 만료되었습니다.")
    touch_worker(session, body)
    call.response = None if body.error else validate_response(call, body.response)
    call.status = "failed" if body.error else "succeeded"
    call.error_code = "MODEL_INFERENCE_FAILED" if body.error else None
    # Lock the job after the call to make cancel/result races deterministic.
    job = session.scalar(
        select(Job)
        .where(Job.id == job.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if job.status not in {"waiting_ai", "queued", "running"} or (
        call.generation != job.payload.get("_ai_generation", 0)
    ):
        deny(409, "취소되었거나 교체된 작업입니다.")
    if job.status == "waiting_ai":
        job.status = "queued"
    saved_status, job_id = call.status, job.id
    session.commit()
    # Continue the same CPU handler immediately; it yields at the next missing model call.
    # Supabase Cron remains the independent recovery path if this invocation is interrupted.
    from lerny.worker import run_once

    run_once(job_id=job_id)
    return {"status": saved_status}
