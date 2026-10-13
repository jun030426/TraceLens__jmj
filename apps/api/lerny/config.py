import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.engine import make_url


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    database_url: str | None = Field(default=None, repr=False)
    runtime_root: Path = Path.home() / "LernyData"
    deployment: Literal["local", "cloud"] = "local"
    model_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:4b-instruct"
    cookie_secure: bool = False
    allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
    ]
    supabase_url: str = ""
    supabase_service_key: SecretStr = SecretStr("")
    storage_bucket: str = "lerny-materials"
    cloud_file_limit_mb: int = Field(default=50, ge=1, le=100)
    ai_worker_token: SecretStr = SecretStr("")
    cron_secret: SecretStr = SecretStr("")
    database_pool_mode: Literal["session", "transaction"] = "session"

    @model_validator(mode="after")
    def cloud_requirements(self):
        if self.deployment == "cloud":
            if not self.database_url or not self.supabase_url.startswith("https://"):
                raise ValueError("Cloud database and HTTPS Supabase URL are required")
            if not self.supabase_service_key.get_secret_value():
                raise ValueError("Cloud storage server key is required")
            if (
                min(
                    len(self.ai_worker_token.get_secret_value()),
                    len(self.cron_secret.get_secret_value()),
                )
                < 32
            ):
                raise ValueError(
                    "Use separate worker and scheduler secrets of at least 32 characters"
                )
            if self.ai_worker_token == self.cron_secret:
                raise ValueError("Worker and scheduler secrets must differ")
            if (
                not self.cookie_secure
                or not self.allowed_origins
                or any(
                    not origin.startswith("https://") or origin.endswith("/")
                    for origin in self.allowed_origins
                )
            ):
                raise ValueError(
                    "Cloud cookies require exact HTTPS origins without trailing slashes"
                )
        return self


@lru_cache
def settings() -> Settings:
    cloud = os.environ.get("LERNY_DEPLOYMENT") == "cloud" or os.environ.get("VERCEL") == "1"
    root = Path(os.environ.get("LERNY_RUNTIME_ROOT", Path.home() / "LernyData"))
    config = root / "secrets" / "app.json"
    values = json.loads(config.read_text()) if not cloud and config.exists() else {}
    if cloud:
        values.update(
            deployment="cloud",
            cookie_secure=True,
            allowed_origins=[],
            database_pool_mode="transaction",
        )
        if url := os.environ.get("POSTGRES_URL"):
            values["database_url"] = make_url(url).set(drivername="postgresql+psycopg").update_query_dict(
                {"sslmode": "require"}).render_as_string(hide_password=False)
        if origin := os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"):
            values["allowed_origins"] = ["https://" + origin]
        if supabase_url := os.environ.get("SUPABASE_URL"):
            values["supabase_url"] = supabase_url
        if service_key := (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
            values["supabase_service_key"] = service_key
    for field in Settings.model_fields:
        if field == "runtime_root":
            continue
        value = os.environ.get("LERNY_" + field.upper())
        if value is not None:
            values[field] = json.loads(value) if field == "allowed_origins" else value
    if secret := os.environ.get("CRON_SECRET"):
        values["cron_secret"] = secret
    if cloud:
        values["deployment"] = "cloud"
    return Settings(**values, runtime_root=root)
