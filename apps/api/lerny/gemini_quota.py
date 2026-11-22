"""Atomic admission before Gemini calls; waiting never holds a DB connection.

Scopes use the Google project label and model, never the API key or worker host.
The DB clock and committed state survive process restarts and worker changes.
"""
import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, time as day_start, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import ContentGeneration, GeminiPaidCallBudget, GeminiQuota, Material, MaterialVersion, uid

PACIFIC = ZoneInfo("America/Los_Angeles")
_verifying = ContextVar("gemini_verifying", default=False)
_paid_job = ContextVar("gemini_paid_review_job", default=False)
_paid_draft = ContextVar("gemini_paid_draft", default=False)


def paid_weekly_generation(session, config, generation):
    if not config.paid_upload_week(generation.course_id, generation.week):
        return False
    version_ids = [source["version_id"] for source in generation.sources]
    return session.scalar(select(MaterialVersion.id).join(Material, Material.id == MaterialVersion.material_id)
        .where(MaterialVersion.id.in_(version_ids), MaterialVersion.created_at >= config.gemini_paid_uploads_since,
               Material.course_id == generation.course_id, Material.week == generation.week,
               Material.deleted.is_(False), Material.visibility == "public", Material.internal_use == "none",
               Material.kind != "answer").limit(1)) is not None


def paid_document_review(session, job, config):
    from lerny.material_policy import student_source

    row = session.execute(select(MaterialVersion, Material).join(Material, Material.id == MaterialVersion.material_id)
        .where(MaterialVersion.id == job.payload.get("version_id"), Material.course_id == job.course_id)).first()
    if not row or job.payload.get("manual_text"):
        return False
    version, material = row
    if material.deleted or not student_source(material) or Path(version.filename).suffix.lower() != ".pptx":
        return False
    return (config.paid_upload(material.course_id, material.week, version.created_at)
            or (config.instructor_review_from_week is None and material.week == config.gemini_review_week))


@contextmanager
def review_job(session, job, config):
    allowed = False
    paid_draft = False
    if (config.gemini_review_quota_project and config.gemini_review_course_id
            and job.course_id == config.gemini_review_course_id):
        if job.kind == "extract":
            allowed = paid_document_review(session, job, config)
        elif job.kind in {"weekly_content", "questions", "practice_prepare"}:
            generation_id = job.payload.get("generation_id")
            selected = bool(generation_id and generation_id == config.gemini_paid_generation_id)
            if generation_id:
                generation = session.scalar(select(ContentGeneration).where(
                    ContentGeneration.id == generation_id, ContentGeneration.course_id == job.course_id,
                    ContentGeneration.status == "draft"))
                if generation:
                    new_upload = paid_weekly_generation(session, config, generation)
                    legacy_week = config.gemini_review_week is not None and generation.week == config.gemini_review_week
                    allowed = (new_upload or legacy_week) and job.kind == "questions"
                    paid_draft = new_upload or (legacy_week and selected)
    token = _paid_job.set(allowed)
    draft_token = _paid_draft.set(paid_draft)
    try:
        yield
    finally:
        _paid_draft.reset(draft_token)
        _paid_job.reset(token)


@contextmanager
def verification():
    token = _verifying.set(True)
    try:
        yield
    finally:
        _verifying.reset(token)


def request_purpose(path, config):
    if path.endswith(":embedContent"):
        return "embedding"
    if path == "interactions" and _verifying.get() and _paid_job.get() and config.gemini_review_quota_project:
        return "review"
    if path == "interactions" and _paid_draft.get():
        return "draft"
    return "content"


class ProviderDeferred(ValueError):
    def __init__(self, code, retry_at):
        super().__init__(code)
        self.retry_at = retry_at


def next_day(timestamp):
    today = datetime.fromtimestamp(timestamp, PACIFIC).date()
    return datetime.combine(today + timedelta(days=1), day_start(), PACIFIC).timestamp() + 1


def scope(path, payload):
    model = payload.get("model") or path.split(":", 1)[0]
    model = model.removeprefix("models/")
    # Google's retired alias shares the replacement model's quota.
    if model == "gemini-3.5-flash":
        model = "gemini-3.6-flash"
    config = settings()
    project = config.gemini_quota_project
    if request_purpose(path, config) in {"review", "draft"}:
        project = config.gemini_review_quota_project
    return hashlib.sha256(json.dumps([project, model]).encode()).hexdigest()


def db_time(session):
    if session.bind.dialect.name == "postgresql":
        return float(session.scalar(text("SELECT extract(epoch FROM clock_timestamp())")))
    # SQLite is used only by isolated tests.
    return time.time()


def insert_if_missing(session, model, **identity):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(model).values(**identity).on_conflict_do_nothing(index_elements=list(identity)))


def locked_row(session, key):
    insert_if_missing(session, GeminiQuota, key=key)
    return session.scalar(select(GeminiQuota).where(GeminiQuota.key == key).with_for_update())


def reserve_paid_budget(session, policy, purpose):
    from lerny.inference import current_material_version

    if policy is None or purpose not in {"review", "embedding"} or current_material_version() != policy.version_id:
        return
    insert_if_missing(session, GeminiPaidCallBudget, version_id=policy.version_id)
    budget = session.scalar(select(GeminiPaidCallBudget).where(
        GeminiPaidCallBudget.version_id == policy.version_id).with_for_update())
    if budget.review + budget.embedding >= policy.max_new_calls:
        raise ValueError("GEMINI_PAID_CALL_BUDGET_EXCEEDED")
    setattr(budget, purpose, getattr(budget, purpose) + 1)


def live_leases(row, current):
    leases = dict(row.active_leases or {})
    # Adopt a live lease from a worker using the single-slot schema.
    if row.active_token:
        leases.setdefault(row.active_token, row.active_until)
    return {token: expiry for token, expiry in leases.items() if expiry > current}


def store_leases(row, leases):
    row.active_leases = leases
    # Older workers must keep waiting until all concurrent reservations expire.
    token = max(leases, key=leases.get, default=None)
    row.active_token, row.active_until = token, leases.get(token, 0)


def reserve_slot(path, payload):
    """Returns a lease only for an immediate call; otherwise persist nothing and yield."""
    config = settings()
    purpose = "embedding" if path.endswith(":embedContent") else "content"
    rpm = getattr(config, f"gemini_{purpose}_requests_per_minute")
    role = request_purpose(path, config)
    review = role == "review"
    concurrency = config.gemini_review_concurrency if review else 1
    if review and config.gemini_review_requests_per_minute is not None:
        rpm = config.gemini_review_requests_per_minute
    tpm = getattr(config, f"gemini_{purpose}_tokens_per_minute")
    rpd = getattr(config, f"gemini_{purpose}_requests_per_day")
    # Media bytes are transport encoding, not text tokens. Keep text's existing
    # conservative estimate and add validated duration/resolution admission units.
    from lerny.gemini_input import input_units
    units = input_units(payload)
    if units > tpm:
        raise ValueError("GEMINI_INPUT_BUDGET_EXCEEDED")
    key = scope(path, payload)
    try:
        with Session(engine()) as session:
            row = locked_row(session, key)
            current = db_time(session)
            if row.blocked_until > current:
                raise ProviderDeferred(row.blocked_code or "GEMINI_RATE_LIMITED", row.blocked_until)
            day = datetime.fromtimestamp(current, PACIFIC).date().isoformat()
            if row.day != day:
                row.day, row.day_count = day, 0
            if rpd and row.day_count >= rpd:
                raise ProviderDeferred("GEMINI_DAILY_WAIT", next_day(current))
            leases = live_leases(row, current)
            if len(leases) >= concurrency:
                raise ProviderDeferred("GEMINI_PACING_WAIT", max(row.next_at, current + 5))
            recent = [item for item in row.recent if item[0] > current - 60]
            wait_until = row.next_at
            if len(recent) >= rpm:
                wait_until = max(wait_until, recent[-rpm][0] + 60.001)
            total = sum(item[1] for item in recent) + units
            for timestamp, cost in recent:
                if total <= tpm:
                    break
                wait_until = max(wait_until, timestamp + 60.001)
                total -= cost
            if wait_until > current:
                raise ProviderDeferred("GEMINI_PACING_WAIT", wait_until)
            reserve_paid_budget(session, config.gemini_paid_call_budget, role)
            token = uid()
            row.recent = [*recent, [current, units]]
            row.next_at = current + 60 / rpm
            leases[token] = current + 300
            store_leases(row, leases)
            row.day_count += 1
            session.commit()
            return key, token
    except SQLAlchemyError:
        # Never issue unpaced requests when the shared coordinator is unavailable.
        raise ProviderDeferred("GEMINI_QUOTA_UNAVAILABLE", time.time() + 30) from None


def release_slot(lease):
    key, token = lease
    try:
        with Session(engine()) as session:
            row = locked_row(session, key)
            leases = live_leases(row, db_time(session))
            if token in leases:
                del leases[token]
                store_leases(row, leases)
                session.commit()
    except SQLAlchemyError:
        # Fail closed: the bounded lease expires. Do not mask a saved response/error.
        pass


def block_until(path, payload, code, deadline):
    try:
        with Session(engine()) as session:
            row = locked_row(session, scope(path, payload))
            if deadline > row.blocked_until:
                row.blocked_until, row.blocked_code = deadline, code
                session.commit()
    except SQLAlchemyError:
        raise ProviderDeferred("GEMINI_QUOTA_UNAVAILABLE", max(deadline, time.time() + 30)) from None
