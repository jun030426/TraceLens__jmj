"""Python service entrypoint. Vercel routes /api here and serves Vite independently."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "apps/api"))

from lerny.main import app
