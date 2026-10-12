import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str | None = None
    runtime_root: Path = Path.home() / "LernyData"
    model_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:4b-instruct"
    cookie_secure: bool = False


@lru_cache
def settings() -> Settings:
    root = Path(os.environ.get("LERNY_RUNTIME_ROOT", Path.home() / "LernyData"))
    config = root / "secrets" / "app.json"
    values = json.loads(config.read_text()) if config.exists() else {}
    if url := os.environ.get("LERNY_DATABASE_URL"):
        values["database_url"] = url
    return Settings(**values, runtime_root=root)
