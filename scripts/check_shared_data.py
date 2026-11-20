"""Read-only shared DB/files readiness check; never prints private records or keys."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from sqlalchemy import func, select, text
from lerny import storage
from lerny.config import settings
from lerny.db import engine
from lerny.main import SCHEMA_REVISION
from lerny.models import Course, Material, MaterialVersion, User


def main():
    try:
        config = settings()
        if not config.uses_supabase_storage:
            raise ValueError("Shared storage not configured")
        with engine().connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != SCHEMA_REVISION:
                raise ValueError("Schema revision mismatch")
            counts = {model.__tablename__: connection.scalar(select(func.count()).select_from(model))
                      for model in (User, Course, Material, MaterialVersion)}
            versions = connection.execute(select(MaterialVersion.object_key, MaterialVersion.sha256)).all()
            tls = bool(connection.connection.driver_connection.pgconn.ssl_in_use)
        if not tls or not storage.ready():
            raise ValueError("TLS and private bucket required")
        for key, checksum in set(versions):
            if hashlib.sha256(storage.download(key, 100 * 1024 * 1024)).hexdigest() != checksum:
                raise ValueError("File checksum mismatch")
        print(json.dumps({"ready": True, "database_tls": tls, "counts": counts,
                          "verified_files": len(set(versions)), "model_calls_performed": False}))
        return 0
    except Exception as error:
        print(json.dumps({"ready": False, "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
