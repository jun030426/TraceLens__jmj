"""Local application foundation. No student-code executor is connected."""

import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from lerny import auth, cloud_jobs, cloud_uploads, courses, jobs, learning, materials, exams, storage
from lerny.config import settings
from lerny.db import engine
from lerny.retrieval import EMBED_MODEL

SCHEMA_REVISION = "a7b18d65ec90"


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
    app.include_router(cloud_uploads.router)
    app.include_router(cloud_jobs.router)

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
            and origin not in settings().allowed_origins
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

    @app.exception_handler(storage.StorageUnavailable)
    async def storage_unavailable(request, exc):
        return error(request, 503, "STORAGE_UNAVAILABLE", "파일 저장소 연결을 확인해 주세요.", True)

    @app.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok", "service": "lerny-api"}

    @app.get("/api/v1/health/ready")
    def service_ready() -> JSONResponse:
        database, files = "unavailable", "local"
        try:
            with engine().connect() as connection:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                database = "ready" if revision == SCHEMA_REVISION else "migration_required"
        except (RuntimeError, SQLAlchemyError):
            pass
        if settings().deployment == "cloud":
            try:
                files = "ready" if storage.ready() else "private_bucket_required"
            except storage.StorageUnavailable:
                files = "unavailable"
        is_ready = database == "ready" and files in {"ready", "local"}
        return JSONResponse(status_code=200 if is_ready else 503, content={
            "status": "ready" if is_ready else "not_ready",
            "scope": "general_service", "dependencies": {"database": database, "storage": files},
            "ai_required": False})

    @app.get("/api/v1/health/learning", responses={503: {"description": "Quality gates incomplete"}})
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
            if settings().deployment == "cloud":
                raise ValueError("Queue mode: no localhost model probe")
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

    @app.get("/api/v1/ai/status")
    def model_status(session: auth.Db, actor: auth.Actor):
        if settings().deployment == "local":
            return {"status": "local", "message": "로컬 AI 테스트 모드입니다."}
        state = cloud_jobs.ai_status(session)
        return {"status": state, "message": "AI 처리 서버에 연결되어 있어요." if state == "online"
                else "AI 테스트 서버가 오프라인이에요. 요청은 보관되며 서버 연결 후 처리됩니다."}

    return app


app = create_app()
