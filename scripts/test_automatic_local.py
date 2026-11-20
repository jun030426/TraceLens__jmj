"""Disposable localhost PostgreSQL for ingestion tests; never uses app DB settings."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL


def main():
    root = Path(__file__).resolve().parents[1]
    runtime = Path(os.environ.get("LERNY_INGESTION_TEST_ROOT", Path.home() / "LernyData/ingestion-tests"))
    runtime.mkdir(parents=True, exist_ok=True)
    binaries = Path(os.environ.get("LERNY_TEST_PG_BIN", Path.home() / "LernyData/tools/postgresql-17/pgsql/bin"))
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    name = "lerny_test"
    roles = {label: label + "_ingestion_test" for label in ("service_role", "anon", "authenticated")}
    with tempfile.TemporaryDirectory(prefix="pg-", dir=runtime) as directory:
        data = Path(directory) / "data"
        assert Path(directory).resolve().is_relative_to(runtime.resolve())
        subprocess.run([str(binaries / "initdb.exe"), "-D", str(data), "-U", "postgres", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], check=True, capture_output=True, timeout=60, **flags)
        subprocess.run([str(binaries / "pg_ctl.exe"), "-D", str(data), "-l", str(Path(directory) / "postgres.log"),
                        "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, **flags)
        try:
            with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres",
                                 autocommit=True, connect_timeout=5) as admin:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                for label, role in roles.items():
                    admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN {}").format(
                        sql.Identifier(role), sql.SQL("BYPASSRLS" if label == "service_role" else "NOBYPASSRLS")))
            url = URL.create("postgresql+psycopg", host="127.0.0.1", port=port, username="postgres", database=name)
            env = {**os.environ, "PYTHONUTF8": "1", "LERNY_INGESTION_TEST_URL": url.render_as_string(),
                   "LERNY_INGESTION_TEST_ROLES": json.dumps(roles), "LERNY_GEMINI_CALLS_ENABLED": "false",
                   "LERNY_DATABASE_URL": url.render_as_string(), "LERNY_AUTOMATIC_LEARNING_ENABLED": "false", "LERNY_HEYGEN_CALLS_ENABLED": "false", "LERNY_AI_PROVIDER": "ollama", "LERNY_RUNTIME_ROOT": str(runtime), "LERNY_ENV_FILE": str(runtime / "no.env"),
                   "TMP": directory, "TEMP": directory, "PYTHONPATH": str(root / "apps/api")}
            command = [sys.executable, "-m", "pytest", *(sys.argv[1:] or ["apps/api/tests/test_learning.py"]), "-q", "-p", "no:cacheprovider", "--tb=short",
                       "--basetemp", str(Path(directory) / "pytest")]
            return subprocess.run(command, cwd=root, env=env, check=False, timeout=600).returncode
        finally:
            subprocess.run([str(binaries / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, **flags)


if __name__ == "__main__":
    sys.exit(main())
