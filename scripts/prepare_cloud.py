"""One-time schema/bootstrap tool. Reads secrets outside Git; no local service stays running."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_environment(path):
    source = Path(path).resolve()
    if source.is_relative_to(ROOT):
        raise SystemExit("Keep cloud credentials outside the repository")
    values = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
    ):
        raise SystemExit("Use a JSON object of environment variable names and string values")
    if any(not (key.startswith("LERNY_") or key == "CRON_SECRET") for key in values):
        raise SystemExit("Only LERNY_* and CRON_SECRET settings are accepted")
    os.environ.update(values)
    sys.path.insert(0, str(ROOT / "apps/api"))
    return values


def prepare(path, bootstrap):
    values = load_environment(path)
    migration_url = values.get("LERNY_MIGRATION_DATABASE_URL")
    if not migration_url:
        raise SystemExit(
            "Set LERNY_MIGRATION_DATABASE_URL to a direct or session-pooler connection"
        )
    if any("REPLACE" in value for value in values.values()):
        raise SystemExit("Fill in the external config placeholders before preparing the database")
    os.environ["LERNY_DATABASE_URL"] = migration_url
    os.environ["LERNY_DATABASE_POOL_MODE"] = "session"
    from alembic import command
    from alembic.config import Config
    from lerny.config import settings

    settings()  # Validate configuration before any database mutations.
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    print("Cloud schema upgraded. Existing application data was preserved.")
    if bootstrap:
        import runpy

        (settings().runtime_root / "secrets").mkdir(parents=True, exist_ok=True)
        runpy.run_path(str(ROOT / "scripts/bootstrap_operator.py"), run_name="__main__")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path.home() / "LernyData/secrets/cloud-app.json"))
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    prepare(args.config, args.bootstrap)
