import json

import pytest
from lerny.config import Settings, settings
from pydantic import ValidationError


def test_vercel_integration_variables_work_without_PC_config(monkeypatch, tmp_path):
    monkeypatch.delenv("LERNY_DATABASE_URL", raising=False)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/app.json").write_text(json.dumps({"database_url": "local-only-secret"}))
    values = {
        "VERCEL": "1", "LERNY_RUNTIME_ROOT": str(tmp_path),
        "POSTGRES_URL": "postgres://app:example@pooler.example:6543/postgres?supa=integration&pgbouncer=true",
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
    assert "supa=" not in config.database_url and "pgbouncer=" not in config.database_url
    assert "local-only-secret" not in config.database_url


def test_cloud_config_fails_closed_without_exposing_credentials():
    with pytest.raises(ValidationError) as error:
        Settings(deployment="cloud", database_url="private-db-secret")
    assert "private-db-secret" not in str(error.value)


def test_shared_files_require_credentials_without_enabling_cloud_execution():
    with pytest.raises(ValidationError):
        Settings(file_storage="supabase")
    config = Settings(file_storage="supabase", supabase_url="https://project.supabase.co",
                      supabase_service_key="sb_secret_example", ai_provider="gemini")
    assert config.uses_supabase_storage and config.deployment == "local"
    assert not config.gemini_calls_enabled
    assert not Settings().uses_supabase_storage


def test_dashboard_pooler_uri_enables_tls_and_transaction_compatibility(monkeypatch, tmp_path):
    monkeypatch.delenv("LERNY_DATABASE_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("LERNY_DEPLOYMENT", raising=False)
    monkeypatch.setenv("LERNY_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("LERNY_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres.example:example@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres")
    config = settings.__wrapped__()
    assert config.database_pool_mode == "transaction"
    assert "sslmode=require" in config.database_url
    assert config.database_url.startswith("postgresql+psycopg://")


def test_gemini_cloud_execution_requires_dedicated_worker_and_explicit_enable(monkeypatch):
    from lerny import gemini_provider
    config = Settings(deployment="cloud", database_url="postgresql://example",
        supabase_url="https://project.supabase.co", supabase_service_key="sb_secret_example",
        ai_provider="gemini", ai_worker_token="w" * 40, cron_secret="c" * 40,
        cookie_secure=True, allowed_origins=["https://lerny.example"], gemini_api_key="synthetic")
    monkeypatch.setattr(gemini_provider, "settings", lambda: config)
    with pytest.raises(ValueError, match="GEMINI_DEDICATED_WORKER_REQUIRED"):
        gemini_provider.available()
    config.dedicated_worker = True
    with pytest.raises(ValueError, match="GEMINI_CALLS_DISABLED"):
        gemini_provider.available()
    config.gemini_calls_enabled = True
    gemini_provider.available()
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValidationError, match="Dedicated workers"):
        Settings(dedicated_worker=True)
