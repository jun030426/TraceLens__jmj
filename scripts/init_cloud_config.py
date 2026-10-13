"""Create private setup templates and random tokens outside the source tree."""
import json
import os
import secrets
from pathlib import Path

root = Path(os.environ.get("LERNY_RUNTIME_ROOT", Path.home() / "LernyData"))
directory = root / "secrets"
directory.mkdir(parents=True, exist_ok=True)
app_path = directory / "cloud-app.json"
runner_path = directory / "ai-runner.json"
if app_path.exists() or runner_path.exists():
    raise SystemExit("Cloud config already exists; existing credentials were not changed")
worker_token = secrets.token_urlsafe(40)
values = {
    "LERNY_DEPLOYMENT": "cloud",
    "LERNY_DATABASE_URL": "REPLACE_WITH_TRANSACTION_POOLER_SQLALCHEMY_URL",
    "LERNY_MIGRATION_DATABASE_URL": "REPLACE_WITH_DIRECT_OR_SESSION_POOLER_SQLALCHEMY_URL",
    "LERNY_DATABASE_POOL_MODE": "transaction",
    "LERNY_ALLOWED_ORIGINS": '["https://REPLACE.vercel.app"]',
    "LERNY_COOKIE_SECURE": "true",
    "LERNY_SUPABASE_URL": os.environ.get("LERNY_SUPABASE_URL", "https://REPLACE.supabase.co"),
    "LERNY_SUPABASE_SERVICE_KEY": "REPLACE_WITH_SERVER_SECRET_KEY",
    "LERNY_STORAGE_BUCKET": "lerny-materials",
    "LERNY_CLOUD_FILE_LIMIT_MB": "50",
    "LERNY_AI_WORKER_TOKEN": worker_token,
    "CRON_SECRET": secrets.token_urlsafe(40),
    "LERNY_MODEL_NAME": "qwen3:4b-instruct",
}
with app_path.open("x", encoding="utf-8") as output:
    json.dump(values, output, ensure_ascii=False, indent=2)
with runner_path.open("x", encoding="utf-8") as output:
    json.dump({"cloud_url": "https://REPLACE.vercel.app", "worker_token": worker_token,
               "worker_id": "test-pc", "model_url": "http://127.0.0.1:11434",
               "allowed_models": ["qwen3:4b-instruct", "qwen3-embedding:0.6b"]}, output, indent=2)
print("Private setup templates created. Tokens were saved to files, not printed.")
print(app_path)
print(runner_path)
