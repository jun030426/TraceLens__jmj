"""One operator-managed Lerny Google connection; instructors never need Google login."""
import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from lerny.config import settings
from lerny.models import GoogleSlidesServiceConnection, GoogleSlidesOAuthState, Job, now
from lerny.security import Actor, Db, deny, digest

router = APIRouter(prefix="/api/v1/google-slides")
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def configured():
    s = settings()
    return bool(s.google_slides_client_id and s.google_slides_client_secret.get_secret_value()
                and s.google_slides_token_key.get_secret_value() and s.google_slides_redirect_uri)


def cipher():
    try:
        return Fernet(settings().google_slides_token_key.get_secret_value().encode())
    except (ValueError, TypeError):
        raise ValueError("GOOGLE_SLIDES_SETUP_REQUIRED") from None


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise ValueError("GOOGLE_SLIDES_RECONNECT_REQUIRED") from None


def teacher(actor):
    if actor.role not in {"teacher", "admin"}:
        deny()


def token_request(data):
    try:
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(TOKEN_URL, data=data)
        if response.status_code in {400, 401, 403}:
            raise ValueError("GOOGLE_SLIDES_RECONNECT_REQUIRED")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, KeyError):
        raise ValueError("GOOGLE_SLIDES_UNAVAILABLE") from None


def access_token(session):
    if not configured():
        raise ValueError("GOOGLE_SLIDES_SETUP_REQUIRED")
    connection = session.get(GoogleSlidesServiceConnection, "lerny")
    if not connection or SCOPE not in connection.scopes.split():
        raise ValueError("GOOGLE_SLIDES_CONNECT_REQUIRED")
    s = settings()
    data = token_request({"client_id": s.google_slides_client_id,
        "client_secret": s.google_slides_client_secret.get_secret_value(),
        "refresh_token": decrypt(connection.refresh_token), "grant_type": "refresh_token"})
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("GOOGLE_SLIDES_RECONNECT_REQUIRED")
    return token


@router.get("/connection")
def connection_status(session: Db, actor: Actor):
    teacher(actor)
    connection = session.get(GoogleSlidesServiceConnection, "lerny")
    return {"configured": configured(), "connected": bool(connection),
            "connected_at": connection.connected_at if connection else None,
            "scope": "Lerny 공용 연동에서 만든 Google 슬라이드만 접근", "mode": "service",
            "rendering_enabled": settings().heygen_rendering_enabled}


@router.post("/connect")
def connect(session: Db, actor: Actor):
    teacher(actor)
    deny(403, "Google은 Lerny 운영 서버의 공용 연동으로 관리해요. 교수자 계정 연결은 필요하지 않아요.")


def begin_service_connection(session):
    """Operator CLI only, never exposed as an unauthenticated HTTP start endpoint.

    The one-use, expiring state and PKCE verifier authorize this setup callback.
    A NULL owner distinguishes this service setup from obsolete per-user flows.
    """
    if not configured():
        deny(409, "Google 연결 설정이 필요해요. 운영자가 OAuth 클라이언트를 등록한 뒤 연결할 수 있어요.")
    s = settings()
    parsed = urlparse(s.google_slides_redirect_uri)
    if (parsed.path != "/api/v1/google-slides/callback" or parsed.query or parsed.fragment
            or f"{parsed.scheme}://{parsed.netloc}" not in s.allowed_origins):
        deny(503, "Google 연결 주소 설정을 확인해 주세요.")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    session.add(GoogleSlidesOAuthState(state_hash=digest(state), owner_id=None,
        verifier=encrypt(verifier), expires_at=now() + timedelta(minutes=10)))
    session.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": s.google_slides_client_id, "redirect_uri": s.google_slides_redirect_uri,
        "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})}


@router.get("/callback")
def callback(session: Db, state: str = "", code: str = "", error: str = ""):
    pending = session.scalar(select(GoogleSlidesOAuthState).where(
        GoogleSlidesOAuthState.state_hash == digest(state)).with_for_update())
    if not pending or pending.owner_id is not None or pending.expires_at <= now():
        deny(400, "공용 Google 연결 요청이 유효하지 않거나 만료됐어요. 운영자가 연결을 다시 시작해야 해요.")
    verifier = decrypt(pending.verifier)
    session.delete(pending)
    session.commit()  # Single use, including denied/failed callbacks.
    if error or not code:
        return setup_result(False)
    s = settings()
    try:
        data = token_request({"client_id": s.google_slides_client_id,
            "client_secret": s.google_slides_client_secret.get_secret_value(),
            "redirect_uri": s.google_slides_redirect_uri, "code": code,
            "code_verifier": verifier, "grant_type": "authorization_code"})
        # Never pair an old account's refresh token with a newly authorized account.
        refresh = data.get("refresh_token")
        scopes = data.get("scope", "")
        if not refresh or SCOPE not in scopes.split():
            raise ValueError("GOOGLE_SLIDES_RECONNECT_REQUIRED")
        connection = session.get(GoogleSlidesServiceConnection, "lerny")
        if not connection:
            connection = GoogleSlidesServiceConnection(id="lerny")
            session.add(connection)
        connection.refresh_token, connection.scopes = encrypt(refresh), scopes
        connection.connected_at = now()
        for job in session.scalars(select(Job).where(Job.kind == "lecture_slides", Job.status == "waiting_google")):
            job.status, job.error_code, job.lease_until = "queued", None, None
        session.commit()
    except ValueError:
        deny(409, "Google 권한 승인이 완료되지 않았어요. 다시 연결해 주세요.")
    return setup_result(True)


def setup_result(connected):
    title = "Lerny 공용 Google 슬라이드 연결 완료" if connected else "Lerny 공용 Google 연결 취소"
    message = ("서버가 공통 디자인으로 대본별 설명 슬라이드를 준비합니다. 교수자별 Google 로그인은 필요하지 않습니다. "
        "이 창은 닫아도 됩니다. 영상 제작과 학생 공개 설정은 그대로 유지됩니다." if connected else
        "연결 권한이 저장되지 않았습니다. 운영자가 연결을 다시 시작할 수 있습니다.")
    return HTMLResponse(f'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title><style>body{{font:18px/1.7 sans-serif;background:#fafafc;color:#1d1d1f;max-width:680px;margin:12vh auto;padding:32px}}'
        f'h1{{font-size:28px;color:#6941c6}}</style><h1>{title}</h1><p>{message}</p></html>',
        headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})
