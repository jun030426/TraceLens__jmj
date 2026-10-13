"""Vercel entrypoint: one origin for the built React app and the FastAPI API."""

import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "apps/api"))

from lerny.main import app


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "API를 찾을 수 없습니다.")
    public = (ROOT / "public").resolve()
    candidate = (public / path).resolve()
    if candidate.is_relative_to(public) and candidate.is_file():
        return FileResponse(candidate)
    if "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(404)
    index = public / "index.html"
    if not index.is_file():
        raise HTTPException(503, "웹 빌드가 필요합니다.")
    return FileResponse(index)
