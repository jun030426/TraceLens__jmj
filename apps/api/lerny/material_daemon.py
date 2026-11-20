"""Dedicated AWS material worker and periodic cleanup, without a public scheduler."""
import time

from lerny.cloud_jobs import cleanup
from lerny.config import settings
from lerny.worker import run_once


def main():
    if not settings().dedicated_worker:
        raise SystemExit("Dedicated worker configuration required")
    next_cleanup = 0.0
    while True:
        try:
            if time.monotonic() >= next_cleanup:
                cleanup()
                next_cleanup = time.monotonic() + 60
            if not run_once():
                time.sleep(2)
        except Exception as exc:
            # Avoid printing private source, configuration, or database connection strings.
            print("Material worker retry:", type(exc).__name__, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
