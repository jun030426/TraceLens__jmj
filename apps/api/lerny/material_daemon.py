"""Dedicated AWS material worker and periodic cleanup, without a public scheduler."""
import sys
import time

from lerny.cloud_jobs import cleanup
from lerny.config import settings
from lerny.worker import EMBEDDING_JOBS, run_once


def main(role="material"):
    if role not in {"material", "embedding"}:
        raise ValueError("Unknown worker role")
    if not settings().dedicated_worker:
        raise SystemExit("Dedicated worker configuration required")
    next_cleanup = 0.0
    while True:
        try:
            if role == "material" and time.monotonic() >= next_cleanup:
                cleanup()
                next_cleanup = time.monotonic() + 60
            if not run_once(kinds=EMBEDDING_JOBS if role == "embedding" else None,
                            exclude_kinds=EMBEDDING_JOBS if role == "material" else (), worker_kind=role):
                time.sleep(2)
        except Exception as exc:
            # Avoid printing private source, configuration, or database connection strings.
            print("Material worker retry:", type(exc).__name__, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main(*sys.argv[1:])
