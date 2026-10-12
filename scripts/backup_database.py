"""Create a local PostgreSQL archive without writing credentials into arguments."""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

root = Path(os.environ.get("LERNY_RUNTIME_ROOT", Path.home() / "LernyData"))
config = json.loads((root / "secrets/app.json").read_text())
from sqlalchemy.engine import make_url

url = make_url(config["database_url"])
destination = root / "backups" / ("lerny-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".dump")
destination.parent.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PGPASSWORD=url.password)
bin_dir = root / "tools/postgresql-17/pgsql/bin"
subprocess.run([str(bin_dir / "pg_dump.exe"), "-h", url.host, "-p", str(url.port), "-U", url.username,
                "-d", url.database, "-Fc", "-f", str(destination)], env=env, check=True,
               creationflags=subprocess.CREATE_NO_WINDOW)
subprocess.run([str(bin_dir / "pg_restore.exe"), "--list", str(destination)], check=True,
               stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
print("Database archive created and catalog checked:", destination)
print("Original uploaded files remain under data/files; a full restore also needs those files.")
