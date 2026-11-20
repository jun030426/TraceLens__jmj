"""Operator helper. Credentials use the AWS login profile; secret values are never printed."""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tarfile
import time
from pathlib import Path

import boto3
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
REGION = "ap-southeast-2"
BUCKET = "lerny-deploy-604472166923-ap-southeast-2"
INSTANCE = "i-0c64182a7dada987a"
PARAMETER = "/lerny/production/worker-env"


def configuration(env_file, state_dir, enable_automatic=False):
    source = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
    names = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SECRET_KEY", "GEMINI_EMBEDDING_API_KEY",
             "GEMINI_CONTENT_API_KEY", "GEMINI_CONTENT_MODEL", "HEYGEN_API_KEY", "HEYGEN_AVATAR_ID", "HEYGEN_VOICE_ID")
    config = {name: source[name] for name in names if source.get(name)}
    assert all(config.get(k) for k in names[:5])
    private = state_dir / "deployment-secrets.json"
    if private.exists():
        generated = json.loads(private.read_text())
    else:
        generated = {"LERNY_AI_WORKER_TOKEN": secrets.token_urlsafe(36), "CRON_SECRET": secrets.token_urlsafe(36)}
        private.write_text(json.dumps(generated))
    config.update(generated)
    config.update({
        "LERNY_DEPLOYMENT": "cloud", "LERNY_AI_PROVIDER": "gemini",
        "LERNY_GEMINI_CALLS_ENABLED": "false", "LERNY_COOKIE_SECURE": "true",
        "LERNY_ALLOWED_ORIGINS": json.dumps(["https://lerny-ten.vercel.app", "https://lerny-kigkig495-2084s-projects.vercel.app"]),
        "LERNY_DATABASE_POOL_MODE": "transaction", "LERNY_RAG_STORAGE": "supabase",
        "LERNY_FILE_STORAGE": "supabase", "LERNY_STORAGE_BUCKET": "lerny-materials",
        "LERNY_CLOUD_FILE_LIMIT_MB": "50",
    })
    if enable_automatic:
        assert config.get("HEYGEN_API_KEY"), "HeyGen server configuration required"
        config.update({"LERNY_GEMINI_CALLS_ENABLED": "true", "LERNY_AUTOMATIC_LEARNING_ENABLED": "true",
                       "LERNY_HEYGEN_CALLS_ENABLED": "true"})
    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "install", "send", "poll", "vercel-env"])
    parser.add_argument("--file")
    parser.add_argument("--id")
    parser.add_argument("--env-file")
    parser.add_argument("--private-dir")
    parser.add_argument("--cli")
    parser.add_argument("--enable-automatic-learning", action="store_true")
    args = parser.parse_args()
    state = Path(args.private_dir) if args.private_dir else ROOT.parent
    session = boto3.Session(profile_name="lerny-deploy", region_name=REGION)
    ssm = session.client("ssm")
    if args.action == "package":
        archive = ROOT.parent / "source.tar.gz"
        excluded = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".venv"}
        with tarfile.open(archive, "w:gz") as out:
            for rel in ["apps/api", "deploy", "pyproject.toml", "uv.lock"]:
                path = ROOT / rel
                files = sorted(path.rglob("*")) if path.is_dir() else [path]
                for file in files:
                    if not file.is_file() or excluded.intersection(file.parts) or file.name.startswith(".env"):
                        continue
                    out.add(file, arcname=file.relative_to(ROOT).as_posix(), recursive=False)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        key = "releases/" + digest + "/source.tar.gz"
        session.client("s3").upload_file(str(archive), BUCKET, key)
        data = {"digest": digest, "key": key, "bytes": archive.stat().st_size}
        (ROOT.parent / "release.json").write_text(json.dumps(data))
        print(json.dumps(data))
    elif args.action == "install":
        config = configuration(args.env_file, state, args.enable_automatic_learning)
        config.update({"LERNY_DEDICATED_WORKER": "true", "LERNY_TRACE_BACKEND": "command",
            "LERNY_TRACE_SANDBOX_COMMAND": json.dumps(["/usr/bin/python3", "/opt/lerny/current/deploy/trace-sandbox/run_isolated.py"])})
        value = json.dumps(config)
        assert len(value.encode()) <= 4096, "Standard parameter limit exceeded"
        ssm.put_parameter(Name=PARAMETER, Value=value, Type="SecureString", Tier="Standard", Overwrite=True)
        release = json.loads((ROOT.parent / "release.json").read_text())
        script = (ROOT / "deploy/aws/remote_install.py").read_text()
        command = "set -eu\ntest -f /var/lib/lerny-bootstrap-ready\npython3 - " + " ".join([BUCKET, release["key"], release["digest"], REGION]) + " <<'LERNY_INSTALL'\n" + script + "\nLERNY_INSTALL\n"
        response = ssm.send_command(InstanceIds=[INSTANCE], DocumentName="AWS-RunShellScript", Parameters={"commands": [command], "executionTimeout": ["1800"]})
        print(json.dumps({"command_id": response["Command"]["CommandId"]}))
    elif args.action == "send":
        command = Path(args.file).read_text(encoding="utf-8-sig")
        response = ssm.send_command(InstanceIds=[INSTANCE], DocumentName="AWS-RunShellScript", Parameters={"commands": [command], "executionTimeout": ["900"]})
        print(json.dumps({"command_id": response["Command"]["CommandId"]}))
    elif args.action == "poll":
        response = ssm.get_command_invocation(CommandId=args.id, InstanceId=INSTANCE)
        print(json.dumps({"status": response["Status"], "code": response["ResponseCode"], "out": response.get("StandardOutputContent", "")[-7000:], "error": response.get("StandardErrorContent", "")[-5000:]}))
    elif args.action == "vercel-env":
        config = configuration(args.env_file, state, args.enable_automatic_learning)
        config["LERNY_SUPABASE_URL"] = config.pop("SUPABASE_URL")
        config["LERNY_SUPABASE_SERVICE_KEY"] = config.pop("SUPABASE_SECRET_KEY")
        config.update({"LERNY_RUNTIME_ROOT": "/tmp/lerny", "LERNY_DEDICATED_WORKER": "false", "LERNY_TRACE_BACKEND": "queue"})
        for name, value in config.items():
            secret = name in {"DATABASE_URL", "LERNY_SUPABASE_SERVICE_KEY", "GEMINI_EMBEDDING_API_KEY", "GEMINI_CONTENT_API_KEY", "HEYGEN_API_KEY", "LERNY_AI_WORKER_TOKEN", "CRON_SECRET"}
            proc = subprocess.run(["node", args.cli, "env", "add", name, "--environment", "production", "--force", "--yes", "--sensitive" if secret else "--no-sensitive", "--non-interactive", "--scope", "team_DZQ8JjviWDvyTXYP4hYjpoAJ"], input=value, text=True, encoding="utf-8", errors="replace", capture_output=True, cwd=ROOT)
            if proc.returncode and "already exists" in proc.stdout + proc.stderr:
                proc = subprocess.run(["node", args.cli, "env", "update", name, "--environment", "production", "--yes", "--type", "secret" if secret else "config", "--non-interactive", "--scope", "team_DZQ8JjviWDvyTXYP4hYjpoAJ"], input=value, text=True, encoding="utf-8", errors="replace", capture_output=True, cwd=ROOT)
            # CLI errors are redacted because validation could echo input values.
            print(json.dumps({"variable": name, "updated": proc.returncode == 0}), flush=True)
            if proc.returncode:
                error = proc.stdout + proc.stderr
                for private_value in config.values():
                    if len(private_value) > 10:
                        error = error.replace(private_value, "[REDACTED]")
                print(error[-1500:])
                raise SystemExit("Environment update failed; inspect metadata only")


if __name__ == "__main__":
    main()
