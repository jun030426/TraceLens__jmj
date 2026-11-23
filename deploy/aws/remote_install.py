"""Invoked by SSM as root; downloads a private, hash-checked release and configuration."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import boto3

SYSTEM_PYTHON = "/usr/bin/python3.12"
RELEASES = Path("/opt/lerny/releases")
RUNTIMES = Path("/opt/lerny/runtimes")
CHECK_IMPORTS = '''
import importlib
import sys
from pathlib import Path

source = Path(sys.argv[1])
if not Path(sys.executable).samefile(sys.argv[2]):
    raise SystemExit("unexpected Python interpreter")
for name in sys.argv[3:]:
    module = importlib.import_module(name)
    if not Path(module.__file__).resolve().is_relative_to(source):
        raise SystemExit("unexpected worker module path")
'''


def prepare_runtime(release):
    runtime = RUNTIMES / release.name
    marker = runtime / ".synced"
    if not marker.is_file():
        # Build away from the live interpreter. uv can replace its target during sync.
        runtime.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as bootstrap:
            tools = Path(bootstrap) / "bin"
            subprocess.run([SYSTEM_PYTHON, "-m", "venv", bootstrap], check=True)
            subprocess.run([tools / "python", "-m", "pip", "install", "uv==0.13.7"], check=True)
            env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(runtime), UV_CACHE_DIR="/var/cache/lerny-uv",
                       UV_PYTHON_DOWNLOADS="never", UV_PYTHON_PREFERENCE="only-system")
            subprocess.run([tools / "uv", "sync", "--python", SYSTEM_PYTHON, "--no-managed-python",
                            "--no-python-downloads", "--frozen", "--no-dev", "--extra", "engine-media"],
                           cwd=release, env=env, check=True)
        marker.touch()
    return runtime


def check_accounts(release, runtime):
    source = release / "apps/api"
    for account, modules in (
        ("lerny-worker", ["lerny.material_daemon", "lerny.video_worker"]),
        ("lerny-code", ["lerny.tracing.cloud_worker"]),
    ):
        subprocess.run(["runuser", "-u", account, "--", "env", "-i", "PATH=/usr/bin:/bin",
                        "PYTHONPATH=" + str(source), "PYTHONNOUSERSITE=1", runtime / "bin/python",
                        "-B", "-P", "-c", CHECK_IMPORTS, source, SYSTEM_PYTHON, *modules],
                       cwd="/", check=True)


def install(bucket, key, digest, region):
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    body = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=key)["Body"].read()
    assert hashlib.sha256(body).hexdigest() == digest
    release = RELEASES / digest
    release.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        archive.extractall(release, filter="data")
    # Secrets stay in memory and a root-only runtime file, never SSM command/log text.
    value = boto3.client("ssm", region_name=region).get_parameter(
        Name="/lerny/production/worker-env", WithDecryption=True)["Parameter"]["Value"]
    config = json.loads(value)
    assert config["LERNY_GEMINI_CALLS_ENABLED"] in {"true", "false"}
    runtime = prepare_runtime(release)
    subprocess.run([sys.executable, str(release / "deploy/aws/install_media.py")], check=True)
    check_accounts(release, runtime)
    activate(release, config)
    print(json.dumps({"release": digest, "installed": True, "services_started": False}))


def activate(release, config):
    subprocess.run(["docker", "build", "-f", "deploy/trace-sandbox/Dockerfile", "-t", "lerny-trace:20261110", "."], cwd=release, check=True)
    secret = Path("/etc/lerny/worker.json")
    fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(config, out)
    current = Path("/opt/lerny/current")
    temporary = Path("/opt/lerny/current-next")
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(release, target_is_directory=True)
    temporary.replace(current)
    for name in ["lerny-code", "lerny-material", "lerny-embedding", "lerny-interactive", "lerny-video"]:
        unit = release / "deploy/aws" / (name + ".service")
        Path("/etc/systemd/system", unit.name).write_bytes(unit.read_bytes())
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def main():
    try:
        install(*sys.argv[1:])
    except Exception:
        print(json.dumps({"installed": False, "services_started": False}), flush=True)
        raise


if __name__ == "__main__":
    main()
