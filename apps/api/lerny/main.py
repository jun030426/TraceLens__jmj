"""Local application foundation. No student-code executor is connected."""

import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from lerny import auth, courses, jobs, learning, materials, exams
from lerny.config import settings
from lerny.db import engine
from lerny.retrieval import EMBED_MODEL


class Capabilities(BaseModel):
    learning: bool = False
    local_ai: bool = True
    code_execution: bool = False
    reason: str = "execution_and_quality_gates_pending"
    identity_and_courses: bool = True
    materials: bool = True
    theory_preview: bool = True
    professor_analytics: bool = True


def create_app() -> FastAPI:
    app = FastAPI(title="Lerny API", version="0.1.0")
    app.include_router(auth.router)
    app.include_router(courses.router)
    app.include_router(materials.router)
    app.include_router(jobs.router)
    app.include_router(learning.router)
    app.include_router(exams.router)

    def error(request, status, code, message, retryable=False):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
                }
            },
        )

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        origin = request.headers.get("origin")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and origin
            and origin
            not in (
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:8000",
            )
        ):
            return error(request, 403, "ORIGIN_DENIED", "요청 출처를 확인해 주세요.")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 422, "INVALID_INPUT", "입력 항목과 형식을 확인해 주세요.")

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return error(request, 409, "CONFLICT", "이미 존재하거나 다른 변경과 충돌하는 요청입니다.")

    @app.exception_handler(OperationalError)
    async def database_unavailable(request, exc):
        return error(
            request, 503, "DATABASE_UNAVAILABLE", "데이터베이스 연결을 확인해 주세요.", True
        )

    @app.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok", "service": "lerny-api"}

    @app.get("/api/v1/health/ready", responses={503: {"description": "Setup incomplete"}})
    def ready() -> JSONResponse:
        # A running HTTP process is not a working learning service.
        database = "not_configured"
        model = "unavailable"
        try:
            with engine().connect() as connection:
                connection.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
                database = "ready"
        except (RuntimeError, OperationalError):
            pass
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(settings().model_url + "/api/tags")
                response.raise_for_status()
                names = {item["name"] for item in response.json().get("models", [])}
                model = (
                    "installed"
                    if {settings().model_name, EMBED_MODEL} <= names
                    else "models_missing"
                )
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "dependencies": {
                    "database": database,
                    "local_model": model,
                    "sandbox": "disabled",
                },
            },
        )

    @app.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        return Capabilities()

    return app


app = create_app()
