import json

import pytest
from lerny.config import Settings, settings
from pydantic import ValidationError


def test_vercel_integration_variables_work_without_PC_config(monkeypatch, tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/app.json").write_text(json.dumps({"database_url": "local-only-secret"}))
    values = {
        "VERCEL": "1", "LERNY_RUNTIME_ROOT": str(tmp_path),
        "POSTGRES_URL": "postgres://app:example@pooler.example:6543/postgres",
        "SUPABASE_URL": "https://project.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_example",
        "VERCEL_PROJECT_PRODUCTION_URL": "lerny.example", "LERNY_AI_WORKER_TOKEN": "w" * 40,
        "CRON_SECRET": "c" * 40,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    config = settings.__wrapped__()
    assert config.deployment == "cloud" and config.cookie_secure
    assert config.allowed_origins == ["https://lerny.example"]
    assert config.database_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in config.database_url
    assert "local-only-secret" not in config.database_url


def test_cloud_config_fails_closed_without_exposing_credentials():
    with pytest.raises(ValidationError) as error:
        Settings(deployment="cloud", database_url="private-db-secret")
    assert "private-db-secret" not in str(error.value)
