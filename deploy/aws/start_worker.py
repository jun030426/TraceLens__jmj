"""Read root-owned runtime configuration, then drop privileges before loading the app."""
import json
import os
import pwd
import sys
from pathlib import Path

kind = sys.argv[1]
if kind not in {"code", "material", "embedding", "interactive", "video"}:
    raise SystemExit(2)
config = json.loads(Path("/etc/lerny/worker.json").read_text())
os.environ.update(config)
os.environ["LERNY_RUNTIME_ROOT"] = "/var/lib/lerny-" + ("code" if kind == "code" else "worker")
account = pwd.getpwnam("lerny-code" if kind == "code" else "lerny-worker")
os.initgroups(account.pw_name, account.pw_gid)
os.setgid(account.pw_gid)
os.setuid(account.pw_uid)
os.environ["HOME"] = account.pw_dir
os.environ["PYTHONPATH"] = "/opt/lerny/current/apps/api"
os.chdir(account.pw_dir)
module = {"code": "lerny.tracing.cloud_worker", "video": "lerny.video_worker"}.get(kind, "lerny.material_daemon")
python = "/opt/lerny/venv/bin/python"
os.execv(python, [python, "-m", module, *([kind] if module == "lerny.material_daemon" else [])])
