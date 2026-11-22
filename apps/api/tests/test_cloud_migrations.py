"""Exercise the real Alembic upgrade/downgrade in an isolated schema on the local test DB."""
import uuid
import pytest
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
        previous = "af3e227a01db"
        command.upgrade(config, previous)
        with isolated.begin() as connection:
            connection.execute(text("""INSERT INTO gemini_quotas
                (key,next_at,active_until,active_token,blocked_until,recent,day,day_count)
                VALUES ('legacy',10,300,'old-token',0,'[]','test',1)"""))
        command.upgrade(config, "head")
        assert set(Base.metadata.tables) <= set(inspect(isolated).get_table_names())
        with isolated.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "b60d9c84f210"
            protected = connection.execute(text(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind='r' AND c.relrowsecurity"
            ), {"schema": schema}).scalars().all()
            assert set(Base.metadata.tables) <= set(protected)
        command.downgrade(config, previous)
        assert "gemini_paid_call_budgets" not in inspect(isolated).get_table_names()
        with isolated.connect() as connection:
            assert connection.execute(text("SELECT active_token,active_until,day_count FROM gemini_quotas "
                                           "WHERE key='legacy'")).one() == ("old-token",300,1)
        with pytest.raises(RuntimeError,match="connection history"):
            command.downgrade(config, "base")
        assert "content_generations" in inspect(isolated).get_table_names()
    finally:
        isolated.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
