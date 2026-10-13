"""Durable model calls: suspend cloud jobs instead of waiting on a PC HTTP server."""

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import ModelCall

_context = ContextVar("inference_job", default=None)


class ModelPending(Exception):
    pass


@contextmanager
def job_context(job):
    token = _context.set((job.id, job.payload.get("_ai_generation", 0)))
    try:
        yield
    finally:
        _context.reset(token)


def perform(operation, body):
    if settings().deployment == "local":
        with httpx.Client(timeout=120, trust_env=False) as client:
            result = client.post(settings().model_url + "/api/" + operation, json=body)
            result.raise_for_status()
            return result.json()
    context = _context.get()
    if context is None:
        raise RuntimeError("Cloud inference requires a durable job context")
    job_id, generation = context
    payload = {"operation": operation, "body": body}
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # Separate transaction survives rollback of a suspended application handler.
    with Session(engine()) as session:
        call = session.scalar(
            select(ModelCall).where(
                ModelCall.job_id == job_id,
                ModelCall.generation == generation,
                ModelCall.fingerprint == fingerprint,
            )
        )
        if call and call.status == "succeeded":
            return call.response
        if call and call.status == "failed":
            raise ValueError("MODEL_INFERENCE_FAILED")
        if not call:
            session.add(
                ModelCall(
                    job_id=job_id, generation=generation, fingerprint=fingerprint, request=payload
                )
            )
            session.commit()
    raise ModelPending()
