"""Inspect or explicitly run the local Gemini API/worker without changing saved settings.

The private launcher's loopback-only guard intentionally remains untouched.
This separate entry point permits the fixed Gemini endpoint only after an operator opts in.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps/api"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "api", "worker"))
    parser.add_argument("--runtime-root", type=Path, default=Path.home() / "LernyPrivateData")
    parser.add_argument("--enable-api-calls", action="store_true")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    if root.is_relative_to(REPO) or not (root / "secrets/app.json").is_file():
        parser.error("Use an existing private runtime outside the source repository.")
    if os.environ.get("VERCEL") == "1" or os.environ.get("LERNY_DEPLOYMENT") == "cloud":
        parser.error("This entry point is local-only.")
    if not 1024 <= args.port <= 65535:
        parser.error("Use a valid non-privileged local port.")
    os.environ.update(
        LERNY_RUNTIME_ROOT=str(root),
        LERNY_DEPLOYMENT="local",
        LERNY_AI_PROVIDER="gemini",
        LERNY_GEMINI_CALLS_ENABLED="true" if args.enable_api_calls else "false",
    )
    from lerny.config import settings
    from sqlalchemy.engine import make_url

    config = settings()
    url = make_url(config.database_url) if config.database_url else None
    if url is None or url.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("An existing loopback PostgreSQL configuration is required.")
    if args.mode == "check":
        print(
            json.dumps(
                {
                    "runtime": str(root),
                    "provider": config.ai_provider,
                    "key_configured": config.gemini_keys_ready(),
                    "calls_enabled": config.gemini_calls_enabled,
                    "database_host": url.host,
                    "database_name": url.database,
                    "network_calls": 0,
                },
                ensure_ascii=False,
            )
        )
        return
    if not args.enable_api_calls:
        from lerny.local_network import guard_loopback
        guard_loopback()
    if args.enable_api_calls and not config.gemini_keys_ready():
        parser.error(
            "Configure Gemini content and embedding credentials in the private team.env file."
        )
    if args.mode == "api":
        import uvicorn

        uvicorn.run("lerny.main:app", host="127.0.0.1", port=args.port, access_log=False)
    else:
        from lerny.worker import run_once

        print("Local Gemini worker: processes Gemini jobs; remote work waits while calls are paused.", flush=True)
        while True:
            if not run_once():
                time.sleep(1)


if __name__ == "__main__":
    main()
