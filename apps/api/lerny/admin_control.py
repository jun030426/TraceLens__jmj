"""Durable server transitions driven by an authenticated scheduler outside the EC2 host."""

from datetime import timedelta

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from lerny import admin_aws
from lerny.admin_models import OperationsWorker, ServerCommand
from lerny.admin_security import audit
from lerny.config import settings
from lerny.db import engine
from lerny.models import User, now
from lerny.operations import busy_counts, state, workers_ready

ACTIVE = ("queued", "draining", "starting", "stopping", "restarting", "uncertain")


def command_view(row):
    return {
        key: getattr(row, key)
        for key in ("id", "action", "status", "reason", "created_at", "finished_at", "error_code")
    }


def finish(session, command, status, code=None):
    command.status, command.error_code, command.finished_at = status, code, now()
    audit(
        session,
        session.get(User, command.actor_id),
        "server_result",
        command.id,
        outcome=status,
        operation=command.action,
        error_code=code,
    )


def advance(session):
    # Claim gates take this same row lock. It closes the last-claim/stop race.
    control = state(session, lock=True)
    control.scheduler_seen_at = now()
    command = session.scalar(
        select(ServerCommand)
        .where(ServerCommand.status.in_(ACTIVE))
        .order_by(ServerCommand.created_at)
        .with_for_update()
        .limit(1)
    )
    if not command:
        session.commit()
        return
    if now() - command.created_at > timedelta(minutes=20):
        finish(session, command, "failed", "SERVER_TRANSITION_TIMEOUT")
        session.commit()
        return  # Keep admission held until an explicit, verified resume.
    try:
        observed = admin_aws.describe()["state"]
        if observed == "stopped" and settings().admin_instance_id:
            # Only the confirmed stopped host can have its stale busy markers retired.
            session.execute(
                update(OperationsWorker)
                .where(OperationsWorker.server_id == settings().admin_instance_id)
                .values(busy=False, ready=False)
            )
        if command.status == "uncertain":
            if command.sent_at and command.sent_at > now() - timedelta(seconds=90):
                session.commit()
                return
            if command.action == "stop" and observed == "stopped":
                finish(session, command, "succeeded")
            elif (
                command.action == "start"
                and observed == "running"
                and workers_ready(session, command.sent_at)
            ):
                control.server_hold = False
                finish(session, command, "succeeded")
            else:
                finish(session, command, "needs_attention", "AWS_RESULT_UNCERTAIN")
            session.commit()
            return
        if command.action == "stop" and observed == "stopped":
            finish(session, command, "succeeded")
        elif command.status in {"starting", "restarting"}:
            if observed == "running" and workers_ready(session, command.sent_at):
                control.server_hold = False
                finish(session, command, "succeeded")
        elif command.status == "stopping":
            if command.action == "restart" and observed == "stopped":
                send(session, command, "starting", admin_aws.start)
                return
        elif command.action == "start":
            if observed == "running":
                if workers_ready(session):
                    control.server_hold = False
                    finish(session, command, "succeeded")
                else:
                    command.status = "starting"
            elif observed == "stopped":
                send(session, command, "starting", admin_aws.start)
                return
            else:
                finish(session, command, "failed", "SERVER_STATE_CONFLICT")
        elif observed != "running":
            finish(session, command, "failed", "SERVER_STATE_CONFLICT")
        elif any(busy_counts(session).values()):
            command.status = "draining"
        else:
            send(session, command, "stopping", admin_aws.stop)
            return
        session.commit()
    except (BotoCoreError, ClientError, ValueError, KeyError, IndexError):
        finish(session, command, "failed", "AWS_CONTROL_UNAVAILABLE")
        session.commit()


def send(session, command, next_status, operation):
    # Record intent BEFORE a non-transactional AWS call. Crash recovery never blindly resends.
    command.status, command.sent_at = "uncertain", now()
    session.commit()
    try:
        request_id = operation()
    except (BotoCoreError, ClientError, ValueError):
        command.error_code = "AWS_RESULT_UNCERTAIN"
        session.commit()
        return
    command.request_id, command.status = request_id, next_status
    session.commit()


def tick():
    with Session(engine()) as session:
        advance(session)
