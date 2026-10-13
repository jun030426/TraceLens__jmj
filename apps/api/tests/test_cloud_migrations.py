"""Exercise the real Alembic upgrade/downgrade in an isolated schema on the local test DB."""
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from lerny import db as db_module
from lerny.models import Base
from sqlalchemy import create_engine, inspect, text


def test_cloud_schema_migration_roundtrip(monkeypatch):
    url = db_module.engine().url.set(database="lerny_test")
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.database == "lerny_test"
    schema = "cloud_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    monkeypatch.setattr(db_module, "engine", lambda: isolated)
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        command.upgrade(config, "head")
        assert set(Base.metadata.tables) <= set(inspect(isolated).get_table_names())
        with isolated.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "a7b18d65ec90"
            protected = connection.execute(text(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind='r' AND c.relrowsecurity"
            ), {"schema": schema}).scalars().all()
            assert set(Base.metadata.tables) <= set(protected)
        command.downgrade(config, "base")
        assert set(inspect(isolated).get_table_names()) <= {"alembic_version"}
    finally:
        isolated.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
