"""Build the Vite app into Vercel's public directory; never migrate a DB at build time."""

import os
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
npm = "npm.cmd" if os.name == "nt" else "npm"
subprocess.run([npm, "ci", "--prefix", "apps/web"], cwd=root, check=True)
subprocess.run([npm, "run", "build", "--prefix", "apps/web"], cwd=root, check=True)
shutil.copytree(root / "apps/web/dist", root / "public", dirs_exist_ok=True)
