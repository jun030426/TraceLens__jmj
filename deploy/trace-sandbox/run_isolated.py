#!/usr/bin/env python3
"""Trusted Linux launcher: bounded output/time and guaranteed disposable-container cleanup."""
import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

MAX_OUTPUT = 6 * 1024 * 1024
IMAGE = "lerny-trace:20261110"


def main():
    args = sys.argv[1:]
    if len(args) != 5 or args[:4] != ["python", "-m", "lerny.tracing.runner", "--language"] or args[4] not in {"c", "java", "python"}:
        return 2
    source = sys.stdin.buffer.read(32 * 1024 + 1)
    if len(source) > 32 * 1024:
        return 2
    lock_root = Path(os.environ.get("LERNY_SANDBOX_LOCK_DIR", "/var/lib/lerny-code"))
    with (lock_root / "slot.lock").open("a") as lock:
        # Enforce one container across all worker processes, including service restarts.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        name = "lerny-code-" + uuid.uuid4().hex
        command = ["/usr/bin/docker", "run", "--rm", "--init", "--name", name,
            "--label", "lerny.sandbox=true", "-i", "--network", "none", "--read-only",
            "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "128", "--memory", "768m", "--memory-swap", "768m", "--cpus", "1",
            "--ulimit", "nofile=128:128", "--tmpfs", "/tmp:rw,exec,nosuid,size=64m,mode=1777",
            "--log-driver", "none", IMAGE, *args]
        process = None
        def interrupted(signum, frame):
            raise InterruptedError()
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                stdin.write(source)
                stdin.seek(0)
                process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr)
                deadline = time.monotonic() + 35
                while process.poll() is None:
                    if time.monotonic() >= deadline or os.fstat(stdout.fileno()).st_size > MAX_OUTPUT or os.fstat(stderr.fileno()).st_size > 1024 * 1024:
                        return 3
                    time.sleep(0.05)
                if process.returncode or os.fstat(stdout.fileno()).st_size > MAX_OUTPUT:
                    return 4
                stdout.seek(0)
                sys.stdout.buffer.write(stdout.read(MAX_OUTPUT + 1))
                return 0
        finally:
            subprocess.run(["/usr/bin/docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
