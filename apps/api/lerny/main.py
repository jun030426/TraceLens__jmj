"""Authenticated application API; student code executes only in the isolated runner."""

import uuid
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError

from lerny import auth, cloud_jobs, cloud_uploads, courses, jobs, learning, materials, exams, storage
from lerny.config import settings
from lerny.retrieval import EMBED_MODEL
from lerny import lecture_preview
from lerny import lecture_specs
from lerny import lecture_grounding_api
from lerny import heygen_request_preview_api
from lerny import rag_api, narration_lessons
from lerny.tracing import service as team_tracing
from lerny import team_api
from lerny import ingestion_api
from lerny import course_videos
from lerny import practice, quiz_archive
from lerny import learning_insights
from lerny import admin_api
from lerny import weekly_content, google_slides_auth, lecture_slides
from lerny import material_previews
from lerny import health

SCHEMA_REVISION = "f18ab47c9821"


class Capabilities(BaseModel):
    learning: bool = False
    local_ai: bool = True
    code_execution: bool = False
    reason: str | None = None
    identity_and_courses: bool = True
    materials: bool = True
    theory_preview: bool = True
    professor_analytics: bool = True
    code_visualization: bool = False


def create_app() -> FastAPI:
    app = FastAPI(title="Lerny API", version="0.1.0")
    app.include_router(auth.router)
    app.include_router(admin_api.router)
    app.include_router(courses.router)
    app.include_router(materials.router)
    app.include_router(material_previews.router)
    app.include_router(jobs.router)
    app.include_router(learning.router)
    app.include_router(exams.router)
    app.include_router(cloud_uploads.router)
    app.include_router(cloud_jobs.router)
    app.include_router(lecture_preview.router)
    app.include_router(lecture_specs.router)
    app.include_router(lecture_grounding_api.router)
    app.include_router(heygen_request_preview_api.router)
    app.include_router(rag_api.router)
    app.include_router(narration_lessons.router)
    app.include_router(team_tracing.router)
    app.include_router(team_api.router)
    app.include_router(ingestion_api.router)
    app.include_router(course_videos.router)
    app.include_router(practice.router)
    app.include_router(quiz_archive.router)
    app.include_router(learning_insights.router)
    app.include_router(weekly_content.router)
    app.include_router(google_slides_auth.router)
    app.include_router(lecture_slides.router)

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
        from lerny.admin_aws import request_token
        token_context = request_token.set(request.headers.get("x-vercel-oidc-token", "") if os.environ.get("VERCEL") == "1" else "")
        try:
            response = await call_next(request)
        finally:
            request_token.reset(token_context)
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
        deps = health.dependencies(SCHEMA_REVISION)
        is_ready = deps["database"] == "ready" and deps["storage"] in {"ready", "local"}
        return JSONResponse(status_code=200 if is_ready else 503, content={
            "status": "ready" if is_ready else "not_ready",
            "scope": "general_service", "dependencies": deps, "ai_required": False})

    @app.get("/api/v1/health/learning", responses={503: {"description": "Learning dependencies unavailable"}})
    def ready() -> JSONResponse:
        state = health.learning_status(SCHEMA_REVISION)
        return JSONResponse(status_code=200 if state["status"] == "ready" else 503, content=state)

    @app.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        state = health.learning_status(SCHEMA_REVISION)
        return Capabilities(learning=state["learning"], local_ai=settings().ai_provider == "ollama",
                            code_execution=state["code_execution"], code_visualization=state["code_execution"],
                            reason=state["reason"])

    @app.get("/api/v1/ai/status")
    def model_status(session: auth.Db, actor: auth.Actor):
        if settings().ai_provider == "gemini":
            from lerny.gemini_runtime import status as gemini_status
            return gemini_status()
        if settings().deployment == "local":
            try:
                with httpx.Client(timeout=2, trust_env=False) as client:
                    response = client.get(settings().model_url + "/api/tags")
                    response.raise_for_status()
                    names = {item["name"] for item in response.json().get("models", [])}
                if not {settings().model_name, EMBED_MODEL} <= names:
                    return {"status": "offline", "reason": "LOCAL_MODEL_MISSING",
                            "message": "필요한 AI 모델이 없어 학습 준비가 대기 중이에요. 자료 저장과 텍스트 확인은 계속할 수 있어요."}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return {"status": "offline", "reason": "LOCAL_MODEL_UNAVAILABLE",
                        "message": "AI에 연결할 수 없어요. 자료 저장과 텍스트 확인은 계속할 수 있어요."}
            return {"status": "local", "message": "로컬 AI가 연결되어 있어요."}
        state = cloud_jobs.ai_status(session)
        return {"status": state, "message": "AI 처리 서버에 연결되어 있어요." if state == "online"
                else "AI 테스트 서버가 오프라인이에요. 요청은 보관되며 서버 연결 후 처리됩니다."}

    return app


app = create_app()
