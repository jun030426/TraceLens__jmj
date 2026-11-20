"""Bounded provider failures; diagnostics contain no prompts, media, or credentials."""
import hashlib
import json
import re
from datetime import datetime, timezone

MAX_SERVICE_FAILURES = 5
EXHAUSTED = "GEMINI_SERVICE_RETRY_EXHAUSTED"
SAFE_MESSAGES = {
    "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
    "The model is overloaded. Please try again later.",
    "The service is temporarily unavailable.",
    "The service is temporarily overloaded or down.",
    "Service unavailable.",
    "Internal error encountered.",
}


def diagnostic(response, payload, request_hash, failures, retry_round, elapsed):
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    code = error.get("status") or error.get("code")
    code = str(code) if re.fullmatch(r"[A-Za-z_0-9]{1,80}", str(code)) else None
    message = error.get("message")
    # Unknown messages may quote the user's source, API key or request body.
    safe_message = message if isinstance(message, str) and message in SAFE_MESSAGES else None
    request_id = response.headers.get("x-request-id") or response.headers.get("x-goog-request-id")
    if not request_id or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", request_id):
        request_id = None
    model = payload.get("model", "")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", model):
        model = None
    return {"http_status": response.status_code, "provider_code": code,
            "message": safe_message, "message_omitted": safe_message is None,
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "request_id": request_id, "request_hash": request_hash, "model": model,
            "service_failures": failures, "max_service_failures": MAX_SERVICE_FAILURES,
            "retry_round": retry_round, "elapsed_ms": max(0, round(elapsed * 1000)),
            "recorded_at": datetime.now(timezone.utc).isoformat()}


def latest_error(job):
    from lerny.config import settings
    from lerny.gemini_provider import fingerprint
    path = settings().runtime_root / "gemini-calls" / fingerprint((job.id, job.payload.get("_ai_generation", 0))) / "diagnostics/latest.json"
    try:
        detail = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if detail.get("retry_round", 0) != job.payload.get("_gemini_retry_round", 0):
        return None
    return detail


def prepare_retry(job):
    """Only a known explicit HTTP failure can resume the same immutable call cache."""
    if job.error_code == EXHAUSTED:
        job.payload = {**job.payload, "_gemini_retry_round": job.payload.get("_gemini_retry_round", 0) + 1}
    else:
        job.payload = {**job.payload, "_ai_generation": job.payload.get("_ai_generation", 0) + 1}
