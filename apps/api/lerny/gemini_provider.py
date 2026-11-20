"""Explicit local Gemini adapter; adapted from the teammate's rag_mvp provider.

The existing job queue owns execution. No automatic provider fallback or ZIP secrets.
Responses are cached per job before the application transaction commits.
"""

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
import re
import time
from email.utils import parsedate_to_datetime

import httpx

from lerny.config import settings
from lerny.heygen_pilot import job_lock
from lerny.gemini_quota import ProviderDeferred, block_until, next_day, release_slot, reserve_slot

_media_budget = ContextVar("gemini_media_budget", default=False)
_embedding_budget = ContextVar("gemini_embedding_budget", default=0)


@contextmanager
def embedding_call_budget(document_count):
    """Allow one request per distinct source chunk, without changing content quotas."""
    if type(document_count) is not int or not 0 <= document_count <= 5000:
        raise ValueError("EMBEDDING_SOURCE_BUDGET_EXCEEDED")
    token = _embedding_budget.set(document_count)
    try:
        yield
    finally:
        _embedding_budget.reset(token)


@contextmanager
def media_call_budget():
    token = _media_budget.set(True)
    try:
        yield
    finally:
        _media_budget.reset(token)


API_ROOT = "https://generativelanguage.googleapis.com/v1beta/"
EMBED_MODEL = "gemini-embedding-2"
DIMENSIONS = 768
PROFILE = "gemini-embedding-2-768-text-v1"


def retry_deadline(value):
    if not value:
        return None
    try:
        seconds = float(value)
        return time.time() + max(0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        try:
            return parsedate_to_datetime(value).timestamp()
        except (ValueError, TypeError, OverflowError):
            return None


def provider_deadline(response, code):
    """Honor both HTTP Retry-After and Google's structured daily/retry details."""
    current = time.time()
    deadlines = [retry_deadline(response.headers.get("retry-after")) or 0]
    try:
        error = response.json().get("error", {})
        daily = bool(re.search(r"per.?day|daily", json.dumps(error), re.I))
        for detail in error.get("details", []):
            if match := re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", str(detail.get("retryDelay", ""))):
                seconds = float(match[1])
                if math.isfinite(seconds):
                    deadlines.append(current + seconds)
        if code == "GEMINI_RATE_LIMITED" and daily:
            deadlines.append(next_day(current))
    except (ValueError, AttributeError, TypeError):
        pass
    deadline = max(deadlines)
    return deadline if deadline > current else current + (60 if code == "GEMINI_RATE_LIMITED" else 30)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def normalized_vector(vector):
    if (
        not isinstance(vector, list)
        or len(vector) != DIMENSIONS
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
    ):
        raise ValueError("INVALID_GEMINI_EMBEDDING")
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("INVALID_GEMINI_EMBEDDING")
    return [x / norm for x in vector]


def available(purpose="all"):
    config = settings()
    if config.deployment != "local" and not config.dedicated_worker:
        raise ValueError("GEMINI_DEDICATED_WORKER_REQUIRED")
    if not config.gemini_calls_enabled:
        raise ValueError("GEMINI_CALLS_DISABLED")
    if not config.gemini_keys_ready(purpose):
        raise ValueError("GEMINI_KEY_REQUIRED")


def request(path, payload, parse):
    from lerny.inference import current_job, current_retry_round
    from lerny.gemini_failures import diagnostic, MAX_SERVICE_FAILURES, EXHAUSTED

    purpose = "embedding" if path.endswith(":embedContent") else "content"
    available(purpose)
    context = current_job()
    if context is None:
        raise ValueError("GEMINI_JOB_CONTEXT_REQUIRED")
    config = settings()
    # Hash the context rather than accepting a caller-controlled path.
    root = config.runtime_root / "gemini-calls" / fingerprint(context)
    key = fingerprint({"path": path, "payload": payload})
    cache = root / (key + ".json")
    # Quotas apply across jobs. Keep only a hashed credential identifier and deadline.
    limit = config.runtime_root / "gemini-limits" / (fingerprint({
        "credential": config.gemini_key(purpose), "purpose": purpose,
        "model": payload.get("model", path.split(":", 1)[0])}) + ".json")
    with job_lock(root):
        entry = {}
        retry_round = current_retry_round()
        if cache.exists():
            entry = json.loads(cache.read_text(encoding="utf-8"))
            if entry.get("status") == "completed":
                return parse(entry["response"])
            if entry.get("status") != "failed" or entry.get("code") not in {
                "GEMINI_RATE_LIMITED", "GEMINI_TEMPORARILY_UNAVAILABLE"
            }:
                raise ValueError("GEMINI_CALL_UNCERTAIN")
        failures = entry.get("service_failures", 0) if entry.get("retry_round", 0) == retry_round else 0
        if failures >= MAX_SERVICE_FAILURES:
            raise ValueError(EXHAUSTED)
        if limit.exists():
            deferred = json.loads(limit.read_text(encoding="utf-8"))
            if deferred["retry_at"] > time.time():
                raise ProviderDeferred(deferred["code"], deferred["retry_at"])
        ceiling = config.gemini_max_calls_per_media_job if _media_budget.get() else config.gemini_max_calls_per_job
        if purpose == "embedding":
            ceiling = max(ceiling, _embedding_budget.get())
        if not cache.exists() and len(list(root.glob("*.json"))) >= ceiling:
            raise ValueError("GEMINI_CALL_BUDGET_EXCEEDED")
        # Admission happens before marking a request as submitted. A queued wait can resume safely.
        lease = reserve_slot(path, payload)
        started = time.monotonic()
        # No retry after an ambiguous network result. Explicit job retry creates a new generation.
        try:
            save_json(cache, {"status": "submitting"})
            with httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    API_ROOT + path,
                    json=payload,
                    headers={
                        "x-goog-api-key": config.gemini_key(purpose),
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                raw = response.json()
            result = parse(raw)
        except httpx.HTTPStatusError as exc:
            code = (
                "GEMINI_RATE_LIMITED"
                if exc.response.status_code == 429
                else "GEMINI_TEMPORARILY_UNAVAILABLE"
                if exc.response.status_code in {500, 502, 503, 504}
                else "GEMINI_REQUEST_REJECTED"
            )
            if code == "GEMINI_TEMPORARILY_UNAVAILABLE":
                failures += 1
            detail = diagnostic(exc.response, payload, key, failures, retry_round, time.monotonic() - started)
            save_json(root / "diagnostics/latest.json", detail)
            save_json(root / "diagnostics" / (key + ".json"), detail)
            if code == "GEMINI_TEMPORARILY_UNAVAILABLE":
                save_json(root / "diagnostics" / (f"{key}-{retry_round}-{failures}.json"), detail)
            save_json(cache, {"status": "failed", "code": code, "http_status": exc.response.status_code,
                              "service_failures": failures, "retry_round": retry_round})
            if code in {"GEMINI_RATE_LIMITED", "GEMINI_TEMPORARILY_UNAVAILABLE"}:
                deadline = provider_deadline(exc.response, code)
                if code == "GEMINI_TEMPORARILY_UNAVAILABLE":
                    deadline = max(deadline, time.time() + min(300, 30 * 2 ** (failures - 1)))
                save_json(limit, {"code": code, "retry_at": deadline})
                block_until(path, payload, code, deadline)
                if failures >= MAX_SERVICE_FAILURES:
                    raise ValueError(EXHAUSTED) from None
                raise ProviderDeferred(code, deadline) from None
            raise ValueError(code) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            save_json(cache, {"status": "uncertain"})
            raise ValueError("GEMINI_CALL_UNCERTAIN") from None
        finally:
            release_slot(lease)
        save_json(cache, {"status": "completed", "response": raw})
        return result


def perform(operation, body):
    if operation == "embed":
        from lerny.team_engine import ServiceGoogle
        client = ServiceGoogle()
        vectors = [normalized_vector(client.embed(value, query=body.get("task") == "query"))
                   for value in body["input"]]
        return {"embeddings": vectors}
    if operation != "chat":
        raise ValueError("GEMINI_OPERATION_UNSUPPORTED")
    system = "\n".join(x["content"] for x in body["messages"] if x["role"] == "system")
    prompt = "\n".join(x["content"] for x in body["messages"] if x["role"] != "system")

    def parse(raw):
        if raw.get("status") != "completed":
            raise ValueError("INCOMPLETE_GEMINI_RESPONSE")
        value = raw.get("output_text")
        if not isinstance(value, str):
            value = "\n".join(
                p.get("text", "")
                for step in raw.get("steps", [])
                if step.get("type") == "model_output"
                for p in step.get("content", [])
                if p.get("type") == "text"
            )
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise TypeError("INVALID_GEMINI_RESPONSE")
        return {"message": {"content": json.dumps(parsed, ensure_ascii=False)}}

    return request(
        "interactions",
        {
            "model": settings().gemini_answer_model,
            "store": False,
            "system_instruction": system,
            "input": prompt,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": body["format"],
            },
            "generation_config": {"max_output_tokens": 6000, "thinking_level": "low"},
        },
        parse,
    )
