"""Read-only readiness for published learning. Never invokes a model or starts a worker."""
from datetime import timedelta
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from lerny import storage
from lerny.admin_models import OperationsState, OperationsWorker
from lerny.config import settings
from lerny.db import engine
from lerny.models import now
from lerny.tracing import service as tracing


def dependencies(schema_revision):
    database, files = "unavailable", "local"
    try:
        with engine().connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            database = "ready" if revision == schema_revision else "migration_required"
    except (RuntimeError, SQLAlchemyError):
        pass
    if settings().uses_supabase_storage:
        try:
            files = "ready" if storage.ready() else "private_bucket_required"
        except storage.StorageUnavailable:
            files = "unavailable"
    return {"database": database, "storage": files}


def learning_status(schema_revision):
    config = settings()
    deps = dependencies(schema_revision)
    maintenance = hold = False
    content = grading = True
    operations = "unavailable"
    grader = "offline" if config.deployment == "cloud" else "local"
    if deps["database"] == "ready":
        try:
            with Session(engine()) as session:
                row = session.get(OperationsState, 1)
                if row:
                    maintenance, hold = row.maintenance, row.server_hold
                    content, grading = row.features.get("content", True), row.features.get("grading", True)
                operations = "ready"
                if config.deployment == "cloud":
                    query = select(OperationsWorker.id).where(
                        OperationsWorker.kind == "interactive", OperationsWorker.ready.is_(True),
                        OperationsWorker.last_seen_at > now() - timedelta(seconds=90))
                    if config.admin_instance_id:
                        query = query.where(OperationsWorker.server_id == config.admin_instance_id)
                    grader = "ready" if session.scalar(query.limit(1)) else "offline"
        except (RuntimeError, SQLAlchemyError):
            operations = "unavailable"
    sandbox = "disabled"
    if config.trace_backend == "queue" or config.trace_sandbox_command:
        try:
            sandbox = "ready" if deps["database"] == "ready" and tracing.sandbox_ready() else "offline"
        except (RuntimeError, SQLAlchemyError):
            sandbox = "unavailable"
    base_ready = deps["database"] == "ready" and deps["storage"] in {"ready", "local"}
    admitted = operations == "ready" and not maintenance and not hold
    learning = base_ready and admitted and content and grading
    execution = base_ready and admitted and grading and sandbox == "ready"
    complete = learning and execution and grader in {"ready", "local"}
    reasons = [
        (deps["database"] != "ready", "database_" + deps["database"]),
        (deps["storage"] not in {"ready", "local"}, "storage_" + deps["storage"]),
        (operations != "ready", "operations_unavailable"),
        (maintenance, "maintenance"), (hold, "server_hold"),
        (not content, "content_disabled"), (not grading, "grading_disabled"),
        (sandbox != "ready", "sandbox_" + sandbox),
        (grader == "offline", "grading_worker_offline"),
    ]
    reason = next((reason for failed, reason in reasons if failed), None)
    # This describes configuration only; readiness never claims a live AI probe succeeded.
    model = "not_probed"
    if config.ai_provider == "gemini":
        from lerny.gemini_runtime import status
        model = status()["status"]
    return {
        "status": "ready" if complete else "degraded" if learning else "not_ready",
        "scope": "published_learning_and_code_execution",
        "reason": reason, "learning": learning, "code_execution": execution,
        "dependencies": {**deps, "sandbox": sandbox, "grading_worker": grader,
                         "operations": operations, "local_model": model},
        "ai_required": False, "ai_live_verified": False,
    }
