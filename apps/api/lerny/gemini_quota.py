"""Atomic admission before Gemini calls; waiting never holds a DB connection.

Scopes use the Google project label and model, never the API key or worker host.
The DB clock and committed state survive process restarts and worker changes.
"""
import hashlib
import json
import time
from datetime import datetime, time as day_start, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.db import engine
from lerny.models import GeminiQuota, uid

PACIFIC = ZoneInfo("America/Los_Angeles")


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
    return hashlib.sha256(json.dumps([settings().gemini_quota_project, model]).encode()).hexdigest()


def db_time(session):
    if session.bind.dialect.name == "postgresql":
        return float(session.scalar(text("SELECT extract(epoch FROM clock_timestamp())")))
    # SQLite is used only by isolated tests.
    return time.time()


def locked_row(session, key):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(GeminiQuota).values(key=key).on_conflict_do_nothing(index_elements=["key"]))
    return session.scalar(select(GeminiQuota).where(GeminiQuota.key == key).with_for_update())


def reserve_slot(path, payload):
    """Returns a lease only for an immediate call; otherwise persist nothing and yield."""
    config = settings()
    purpose = "embedding" if path.endswith(":embedContent") else "content"
    rpm = getattr(config, f"gemini_{purpose}_requests_per_minute")
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
            if row.active_until > current:
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
            token = uid()
            row.recent = [*recent, [current, units]]
            row.next_at = current + 60 / rpm
            row.active_token, row.active_until = token, current + 300
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
            row = session.scalar(select(GeminiQuota).where(GeminiQuota.key == key).with_for_update())
            if row and row.active_token == token:
                row.active_token, row.active_until = None, 0
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
