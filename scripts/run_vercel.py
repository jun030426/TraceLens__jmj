"""Explicit Vercel CLI invocation; load only deployment credentials from team.env."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.environment import read_env


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("Usage: python scripts/run_vercel.py <vercel arguments>; no command was run.")
        return 0
    executable = shutil.which("vercel.cmd" if os.name == "nt" else "vercel")
    if not executable:
        print("Vercel CLI is not installed or not on PATH.", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    private = read_env()
    for name in ("VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"):
        if not environment.get(name) and private.get(name):
            environment[name] = private[name]
    return subprocess.run([executable, *args], env=environment, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
