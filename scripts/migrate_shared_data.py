"""Additive local-to-Supabase import. Default is a rollback rehearsal, never overwrite.

Pass private env/file/backup paths; no credentials are accepted on the command line.
Snapshots contain private data and must stay outside the source tree.
"""
import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny import storage
from lerny.config import Settings
from lerny.environment import read_env
from lerny.models import Base

# These are machine/session state, not user accounts or durable learning history.
TRANSIENT = {"login_sessions", "login_attempts", "reset_tokens", "ai_workers", "upload_intents"}


class MigrationStopped(Exception):
    pass


def canonical(value):
    # Local Postgres may return +09:00 while Supabase returns the same instant in UTC.
    def encode(item):
        return item.astimezone(UTC).isoformat() if isinstance(item, datetime) else str(item)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=encode)


def snapshot(connection, tables):
    return {table.name: [dict(row) for row in connection.execute(
        select(table).order_by(*table.primary_key.columns)).mappings()] for table in tables}


def additions(tables, source, target):
    result = {}
    for table in tables:
        columns = list(table.primary_key.columns.keys())
        key = lambda row: tuple(row[col] for col in columns)
        existing = {key(row): row for row in target[table.name]}
        rows = []
        for row in source[table.name]:
            old = existing.get(key(row))
            if old is None:
                rows.append(row)
            elif canonical(old) != canonical(row):
                raise MigrationStopped("PRIMARY_KEY_CONTENT_CONFLICT:" + table.name)
        result[table.name] = rows
    return result


def write_snapshot(path, data):
    with path.open("x", encoding="utf-8") as out:
        out.write(canonical(data))


def import_rows(connection, tables, rows):
    for table in tables:
        values = rows[table.name]
        for start in range(0, len(values), 100):
            connection.execute(table.insert(), values[start:start + 100])


def migrate(args):
    source_cfg, target_cfg = read_env(args.source_env), read_env(args.target_env)
    source_url = make_url(source_cfg["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    target_url = make_url(target_cfg["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    if source_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise MigrationStopped("SOURCE_MUST_BE_LOCAL")
    direct_host = "db." + args.project_ref + ".supabase.co"
    if not ((target_url.host == direct_host) or (
        (target_url.host or "").endswith(".pooler.supabase.com")
        and (target_url.username or "").endswith("." + args.project_ref)
    )):
        raise MigrationStopped("TARGET_PROJECT_MISMATCH")
    expected_url = "https://" + args.project_ref + ".supabase.co"
    if target_cfg.get("SUPABASE_URL", "").rstrip("/") != expected_url:
        raise MigrationStopped("STORAGE_PROJECT_MISMATCH")
    target_url = target_url.update_query_dict({"sslmode": "require"})
    config = Settings(file_storage="supabase", supabase_url=expected_url,
        supabase_service_key=target_cfg.get("SUPABASE_SECRET_KEY") or target_cfg.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        storage_bucket=target_cfg.get("LERNY_STORAGE_BUCKET", "lerny-materials"))
    storage.settings = lambda: config
    backup = Path(args.backup_dir).resolve()
    repo = Path(__file__).resolve().parents[1]
    if backup.is_relative_to(repo):
        raise MigrationStopped("BACKUP_MUST_BE_OUTSIDE_SOURCE_TREE")
    backup.mkdir(parents=True, exist_ok=True)
    run_dir = backup / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir()
    file_root = Path(args.source_files).resolve(strict=True)
    tables = [t for t in Base.metadata.sorted_tables if t.name not in TRANSIENT]
    source_engine = create_engine(source_url, hide_parameters=True, connect_args={"connect_timeout": 10})
    target_engine = create_engine(target_url, poolclass=NullPool, hide_parameters=True,
        connect_args={"connect_timeout": 10, "prepare_threshold": None})
    with source_engine.connect().execution_options(isolation_level="REPEATABLE READ") as source:
        source.execute(text("SET TRANSACTION READ ONLY"))
        source_revision = source.scalar(text("SELECT version_num FROM alembic_version"))
        rows = snapshot(source, tables)
        transient_counts = {name: source.scalar(select(text("count(*)")).select_from(Base.metadata.tables[name]))
                            for name in sorted(TRANSIENT)}
        if transient_counts["upload_intents"]:
            raise MigrationStopped("PENDING_UPLOAD_STATE_REQUIRES_REVIEW")
    files = {}
    for version in rows["material_versions"]:
        key = version["object_key"]
        path = (file_root / key).resolve(strict=True)
        if not path.is_relative_to(file_root) or not path.is_file():
            raise MigrationStopped("SOURCE_FILE_OUTSIDE_ROOT")
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if content_hash != version["sha256"]:
            raise MigrationStopped("SOURCE_FILE_HASH_MISMATCH")
        if key in files and files[key][1] != content_hash:
            raise MigrationStopped("SOURCE_OBJECT_KEY_CONFLICT")
        files[key] = (path, content_hash)
    with target_engine.connect() as target:
        target.execute(text("SET TRANSACTION READ ONLY"))
        if target.scalar(text("SELECT version_num FROM alembic_version")) != source_revision:
            raise MigrationStopped("SCHEMA_REVISION_MISMATCH")
        inspector = inspect(target)
        for table in tables:
            if set(table.c.keys()) != {column["name"] for column in inspector.get_columns(table.name, schema="public")}:
                raise MigrationStopped("SCHEMA_COLUMNS_MISMATCH:" + table.name)
        before = snapshot(target, tables)
        objects = set(target.scalars(text("SELECT name FROM storage.objects WHERE bucket_id=:bucket"), {"bucket": config.storage_bucket}))
        tls = bool(target.connection.driver_connection.pgconn.ssl_in_use)
    if not tls or not storage.ready():
        raise MigrationStopped("TLS_OR_PRIVATE_BUCKET_REQUIRED")
    pending = additions(tables, rows, before)
    write_snapshot(run_dir / "source-app-rows.json", rows)
    write_snapshot(run_dir / "target-before-app-rows.json", before)
    summary = {"apply": args.apply, "tls": tls, "source_files": len(files),
        "new_files": len(set(files) - objects), "insert_rows": {k: len(v) for k,v in pending.items()},
        "transient_rows_retained_locally": transient_counts}
    # Rehearse every unique/FK constraint atomically before uploading any file.
    with target_engine.connect() as target:
        transaction = target.begin()
        try:
            import_rows(target, tables, pending)
        finally:
            transaction.rollback()
    summary["database_rehearsal_passed"] = True
    # Never replace an object already present in the shared bucket.
    for key, (path, expected_hash) in files.items():
        if key in objects:
            actual = storage.download(key, max(path.stat().st_size, 1))
            if hashlib.sha256(actual).hexdigest() != expected_hash:
                raise MigrationStopped("REMOTE_OBJECT_HASH_CONFLICT")
    if not args.apply:
        write_snapshot(run_dir / "summary.json", summary)
        print(json.dumps(summary))
        return
    uploaded = []
    for key, (path, expected_hash) in files.items():
        if key not in objects:
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise MigrationStopped("SOURCE_FILE_CHANGED_DURING_IMPORT")
            storage.put(key, content)
            uploaded.append(key)
            write_snapshot(run_dir / ("uploaded-%03d.json" % len(uploaded)), {"key": key, "sha256": expected_hash})
            if hashlib.sha256(storage.download(key, max(len(content), 1))).hexdigest() != expected_hash:
                raise MigrationStopped("UPLOADED_FILE_HASH_MISMATCH")
    # The lock serializes this cutover with app writes. It lasts only for the DB insert.
    with target_engine.begin() as target:
        target.execute(text("SET LOCAL lock_timeout = '5s'"))
        names = ", ".join('public."' + table.name + '"' for table in tables)
        target.execute(text("LOCK TABLE " + names + " IN SHARE ROW EXCLUSIVE MODE"))
        current = snapshot(target, tables)
        import_rows(target, tables, additions(tables, rows, current))
    with target_engine.connect() as target:
        final = snapshot(target, tables)
        if any(additions(tables, rows, final).values()):
            raise MigrationStopped("POST_IMPORT_VERIFICATION_FAILED")
        # All previously existing rows must retain their exact content.
        if any(additions(tables, before, final).values()):
            raise MigrationStopped("EXISTING_DATA_VERIFICATION_FAILED")
    summary.update(verified=True, uploaded_files=len(uploaded),
        final_counts={k: len(v) for k,v in final.items()})
    write_snapshot(run_dir / "summary.json", summary)
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-env", "target-env", "source-files", "backup-dir", "project-ref"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        migrate(args)
    except MigrationStopped as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except Exception as error:
        # Database exceptions may contain parameters/password hashes. Do not log them.
        print(json.dumps({"error": "MIGRATION_FAILED", "type": type(error).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
