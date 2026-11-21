import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.engine import make_url

from lerny.environment import cloud_environment, private_env_path, read_env, runtime_root


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    database_url: str | None = Field(default=None, repr=False)
    runtime_root: Path = Path.home() / "LernyData"
    deployment: Literal["local", "cloud"] = "local"
    model_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:4b-instruct"
    ai_provider: Literal["ollama", "gemini"] = "ollama"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_embedding_api_key: SecretStr = SecretStr("")
    gemini_content_api_key: SecretStr = SecretStr("")
    gemini_calls_enabled: bool = False
    gemini_answer_model: str = Field(default="gemini-3.5-flash-lite", pattern=r"^[A-Za-z0-9._-]+$")
    gemini_max_calls_per_job: int = Field(default=80, ge=1, le=1000)
    # A lecture has hundreds of independently checked speech/frame units.
    # Separate bounded lifetime ceiling; shared minute/day limits still apply.
    gemini_max_calls_per_media_job: int = Field(default=5000, ge=1, le=10000)
    # Application ceilings, not claims about Google's account-specific quotas.
    # All workers/keys in the same Google project must share this scope.
    gemini_quota_project: str = Field(default="lerny", min_length=1, max_length=100)
    # Set on the worker to opt in to verification billed to the embedding project.
    gemini_review_quota_project: str | None = Field(default=None, min_length=1, max_length=100)
    gemini_review_course_id: str | None = None
    gemini_review_week: int | None = Field(default=None, ge=1)
    # The same course can hand PPT and weekly question review to its instructor.
    instructor_review_from_week: int | None = Field(default=None, ge=1)

    gemini_content_requests_per_minute: int = Field(default=12, ge=1, le=6000)
    gemini_embedding_requests_per_minute: int = Field(default=12, ge=1, le=6000)
    gemini_content_tokens_per_minute: int = Field(default=200000, ge=1)
    gemini_embedding_tokens_per_minute: int = Field(default=200000, ge=1)
    # Zero: use provider daily-quota responses until the actual project limit is known.
    gemini_content_requests_per_day: int = Field(default=0, ge=0)
    gemini_embedding_requests_per_day: int = Field(default=0, ge=0)
    cookie_secure: bool = False
    allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
    ]
    supabase_url: str = ""
    supabase_service_key: SecretStr = SecretStr("")
    storage_bucket: str = "lerny-materials"
    file_storage: Literal["local", "supabase"] = "local"
    cloud_file_limit_mb: int = Field(default=50, ge=1, le=100)
    media_storage_enabled: bool = False
    media_storage_url: str = ""
    media_storage_bucket: str = ""
    media_storage_region: str = "ap-southeast-2"
    media_storage_account: str = ""
    media_file_limit_mb: int = Field(default=1024, ge=1, le=1024)
    ai_worker_token: SecretStr = SecretStr("")
    cron_secret: SecretStr = SecretStr("")
    database_pool_mode: Literal["session", "transaction"] = "session"
    rag_storage: Literal["local", "supabase"] = "local"
    # Latest frontend's Java/C trace protocol; empty keeps server execution unavailable.
    trace_sandbox_command: list[str] = []
    trace_backend: Literal["disabled", "command", "queue"] = "disabled"
    dedicated_worker: bool = False
    automatic_learning_enabled: bool = False
    # New billable submissions require a separate explicit operator switch.
    heygen_rendering_enabled: bool = False
    google_slides_client_id: str = ""
    google_slides_client_secret: SecretStr = SecretStr("")
    google_slides_token_key: SecretStr = SecretStr("")
    google_slides_redirect_uri: str = ""
    heygen_calls_enabled: bool = False
    heygen_api_key: SecretStr = SecretStr("")
    admin_mfa_key: SecretStr = SecretStr("")
    admin_server_enabled: bool = False
    admin_aws_region: str = "ap-southeast-2"
    admin_aws_account: str = Field(default="", pattern=r"^(|[0-9]{12})$")
    admin_instance_id: str = Field(default="", pattern=r"^(|i-[0-9a-f]{8,17})$")
    admin_aws_role_arn: str = ""
    admin_control_url: str = ""

    def instructor_reviews_week(self, course_id, week):
        return (self.instructor_review_from_week is not None
                and course_id is not None and course_id == self.gemini_review_course_id
                and week is not None and week >= self.instructor_review_from_week)

    @property
    def uses_supabase_storage(self):
        # Shared data does not require deploying or enabling an AI worker.
        return self.file_storage == "supabase" or self.deployment == "cloud"

    def gemini_key(self, purpose):
        if purpose == "review":
            return self.gemini_embedding_api_key.get_secret_value()
        if purpose not in {"embedding", "content"}:
            raise ValueError("Unknown Gemini purpose")
        dedicated = getattr(self, f"gemini_{purpose}_api_key")
        return dedicated.get_secret_value() or self.gemini_api_key.get_secret_value()

    def gemini_keys_ready(self, purpose="all"):
        if purpose == "any":
            return any(self.gemini_key(p) for p in ("embedding", "content"))
        if purpose == "all":
            return all(self.gemini_key(p) for p in ("embedding", "content"))
        return bool(self.gemini_key(purpose))

    @model_validator(mode="after")
    def cloud_requirements(self):
        if self.uses_supabase_storage and (
            not self.supabase_url.startswith("https://")
            or not self.supabase_service_key.get_secret_value()
        ):
            raise ValueError("Shared files require HTTPS Supabase URL and server key")
        if self.rag_storage == "supabase" and (
            not self.supabase_url.startswith("https://")
            or not self.supabase_service_key.get_secret_value()
        ):
            raise ValueError("Shared RAG requires HTTPS Supabase URL and server key")
        if self.dedicated_worker and os.environ.get("VERCEL") == "1":
            raise ValueError("Dedicated workers cannot run inside Vercel Functions")
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
    cloud = cloud_environment()
    root = runtime_root()
    config = root / "secrets" / "app.json"
    values = json.loads(config.read_text(encoding="utf-8-sig")) if not cloud and config.exists() else {}
    aliases = {
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_EMBEDDING_API_KEY": "gemini_embedding_api_key",
        "GEMINI_CONTENT_API_KEY": "gemini_content_api_key",
        "GEMINI_MODEL": "gemini_answer_model", "GEMINI_CONTENT_MODEL": "gemini_answer_model",
        "DATABASE_URL": "database_url", "SUPABASE_URL": "supabase_url",
        "SUPABASE_SERVICE_ROLE_KEY": "supabase_service_key", "SUPABASE_SECRET_KEY": "supabase_service_key",
        "CRON_SECRET": "cron_secret",
        "HEYGEN_API_KEY": "heygen_api_key",
    }
    def apply(source, *, from_file=False):
        for name, field in aliases.items():
            if source.get(name):
                values[field] = source[name]
        for field in Settings.model_fields:
            if field == "runtime_root" or (from_file and field in {
                "deployment", "ai_provider", "gemini_calls_enabled", "trace_sandbox_command"
            }):
                continue
            if (value := source.get("LERNY_" + field.upper())) is not None and (value or not from_file):
                values[field] = json.loads(value) if field in {"allowed_origins", "trace_sandbox_command"} else value
    if not cloud:
        apply(read_env(private_env_path(root)), from_file=True)
    if cloud:
        values.update(
            deployment="cloud",
            cookie_secure=True,
            allowed_origins=[],
            database_pool_mode="transaction",
        )
        if url := os.environ.get("POSTGRES_URL"):
            values["database_url"] = make_url(url).difference_update_query(
                ["supa", "pgbouncer", "connection_limit", "pool_timeout", "schema"]
            ).set(drivername="postgresql+psycopg").update_query_dict(
                {"sslmode": "require"}).render_as_string(hide_password=False)
        if origin := os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"):
            values["allowed_origins"] = ["https://" + origin]
        if supabase_url := os.environ.get("SUPABASE_URL"):
            values["supabase_url"] = supabase_url
        if service_key := (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
            values["supabase_service_key"] = service_key
    apply(os.environ)
    if cloud:
        values["deployment"] = "cloud"
    if str(values.get("database_url", "")).startswith(("postgres://", "postgresql://")):
        values["database_url"] = make_url(values["database_url"]).set(
            drivername="postgresql+psycopg").render_as_string(hide_password=False)
    if values.get("database_url"):
        url = make_url(values["database_url"])
        if (url.host or "").endswith((".pooler.supabase.com", ".supabase.co")):
            if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                url = url.update_query_dict({"sslmode": "require"})
            if (url.host or "").endswith(".pooler.supabase.com") and url.port == 6543:
                values["database_pool_mode"] = "transaction"
            values["database_url"] = url.render_as_string(hide_password=False)
    return Settings(**values, runtime_root=root)
