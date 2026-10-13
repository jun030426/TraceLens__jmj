"""Export reviewable initial schema SQL for Supabase MCP/SQL Editor without DB credentials."""
import io
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
output = io.StringIO()
config = Config(str(root / "alembic.ini"), output_buffer=output)
config.set_main_option("script_location", str(root / "migrations"))
command.upgrade(config, "head", sql=True)
query = re.sub(r"^(?:BEGIN|COMMIT);\s*$", "", output.getvalue(), flags=re.MULTILINE)
destination = Path(os.environ.get("LERNY_RUNTIME_ROOT", Path.home() / "LernyData")) / "build/cloud_schema.sql"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(query, encoding="utf-8")
print(f"Initial schema SQL exported: {destination}")
