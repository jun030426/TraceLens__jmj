"""Bounded administrative views of current worker health and prior process responses."""
from datetime import timedelta

from sqlalchemy import func, select

from lerny.admin_models import OperationsWorker
from lerny.config import settings
from lerny.models import now
from lerny.operations import REQUIRED_WORKER_KINDS


def scope():
    filters = [OperationsWorker.kind.in_(REQUIRED_WORKER_KINDS)]
    if settings().admin_instance_id:
        # A scheduler/serverless helper heartbeat must not stand in for the AWS worker.
        filters.append(OperationsWorker.server_id == settings().admin_instance_id)
    return filters


def overview(session, control):
    cutoff = now() - timedelta(seconds=90)
    recent = OperationsWorker.last_seen_at > cutoff
    records = session.execute(select(
        OperationsWorker.kind,
        func.max(OperationsWorker.last_seen_at),
        func.count(),
        func.count().filter(recent),
        func.count().filter(recent, OperationsWorker.ready.is_(True)),
    ).where(*scope()).group_by(OperationsWorker.kind)).all()
    grouped = {kind: (last, total, live, ready) for kind, last, total, live, ready in records}
    workers = []
    for kind in REQUIRED_WORKER_KINDS:
        last, total, live, ready = grouped.get(kind, (None, 0, 0, 0))
        status = ("online" if ready else "not_ready" if live else
                  "waiting_response" if control.server_hold or control.maintenance or last is None else "stale")
        workers.append({"kind": kind, "last_seen_at": last, "status": status,
                        "responding": live, "ready": ready})
    return {"workers": workers, "worker_history_count": sum(row[2] for row in records)}


def history(session, *, kind=None, offset=0, limit=5):
    filters = scope()
    if kind:
        filters.append(OperationsWorker.kind == kind)
    total = session.scalar(select(func.count()).select_from(OperationsWorker).where(*filters))
    records = session.scalars(select(OperationsWorker).where(*filters).order_by(
        OperationsWorker.last_seen_at.desc(), OperationsWorker.id.desc()).offset(offset).limit(limit))
    return {"items": [{"id": row.id, "kind": row.kind, "last_seen_at": row.last_seen_at,
                        "ready_at_response": row.ready} for row in records],
            "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total}
