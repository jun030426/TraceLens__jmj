"""Invoked by SSM as root; downloads a private, hash-checked release and configuration."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import boto3

bucket, key, digest, region = sys.argv[1:]
assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
body = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=key)["Body"].read()
assert hashlib.sha256(body).hexdigest() == digest
release = Path("/opt/lerny/releases") / digest
release.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
    archive.extractall(release, filter="data")
# Secrets stay in memory and a root-only runtime file, never SSM command/log text.
value = boto3.client("ssm", region_name=region).get_parameter(
    Name="/lerny/production/worker-env", WithDecryption=True)["Parameter"]["Value"]
config = json.loads(value)
assert config["LERNY_GEMINI_CALLS_ENABLED"] in {"true", "false"}
secret = Path("/etc/lerny/worker.json")
fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump(config, out)
subprocess.run(["python3", "-m", "venv", "/opt/lerny/venv"], check=True)
subprocess.run(["/opt/lerny/venv/bin/pip", "install", "uv==0.13.7"], check=True)
env = dict(os.environ, UV_PROJECT_ENVIRONMENT="/opt/lerny/venv", UV_CACHE_DIR="/var/cache/lerny-uv")
subprocess.run(["/opt/lerny/venv/bin/uv", "sync", "--frozen", "--no-dev", "--extra", "engine-media"], cwd=release, env=env, check=True)
subprocess.run([sys.executable, str(release / "deploy/aws/install_media.py")], check=True)
subprocess.run(["docker", "build", "-f", "deploy/trace-sandbox/Dockerfile", "-t", "lerny-trace:20261110", "."], cwd=release, check=True)
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
print(json.dumps({"release": digest, "installed": True, "services_started": False}))
