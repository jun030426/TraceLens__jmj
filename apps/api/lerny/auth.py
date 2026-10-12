import base64
import io
import warnings
from PIL import Image, ImageOps
import re
import secrets
from datetime import timedelta

from argon2.exceptions import VerificationError
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select

from lerny.config import settings
from lerny.models import AuditEvent, LoginAttempt, LoginSession, ResetToken, User, now
from lerny.security import COOKIE, Actor, Db, create_session, deny, digest, hasher

router = APIRouter(prefix="/api/v1")
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    login_id: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("login_id")
    @classmethod
    def normalize(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[a-z0-9_.@-]+", value):
            raise ValueError("아이디는 영문·숫자와 _.@-를 사용해 주세요.")
        return value


def validate_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
        raise ValueError("올바른 이메일 주소를 입력해 주세요.")
    return value


class Signup(Login):
    email: str = Field(min_length=3, max_length=254)
    _email = field_validator("email")(validate_email)
    major: str | None = Field(default=None, max_length=100)
    student_number: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    privacy_notice_version: str


class ChangePassword(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ResetPassword(Input):
    one_time_token: str = Field(min_length=20, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def public_user(user):
    return {
        k: getattr(user, k)
        for k in (
            "id",
            "login_id",
            "display_name",
            "major",
            "student_number",
            "email",
            "avatar",
            "role",
            "must_change_password",
            "privacy_notice_version",
        )
    }


@router.post("/auth/signup", status_code=201)
def signup(body: Signup, session: Db):
    if body.privacy_notice_version != "2026-10-12":
        deny(422, "현재 개인정보 안내에 동의해 주세요.")
    user = User(
        login_id=body.login_id,
        display_name=body.display_name,
        major=body.major or None,
        student_number=body.student_number or None,
        email=body.email,
        password_hash=hasher.hash(body.password),
        role="student",
        privacy_notice_version=body.privacy_notice_version,
    )
    session.add(user)
    session.commit()
    return {"user_id": user.id}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, session: Db):
    key = digest(body.login_id)
    ipkey = digest("ip:" + (request.client.host if request.client else "unknown"))
    since = now() - timedelta(minutes=15)
    for attempt_key, limit in ((key, 10), (ipkey, 50)):
        count = session.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.key == attempt_key, LoginAttempt.created_at > since)
        )
        if count >= limit:
            deny(429, "로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.")
    user = session.scalar(select(User).where(User.login_id == body.login_id))
    valid = False
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except VerificationError:
        pass
    if not valid or not user or not user.active:
        session.add_all([LoginAttempt(key=key), LoginAttempt(key=ipkey)])
        session.commit()
        deny(401, "아이디 또는 비밀번호를 확인해 주세요.")
    # Revoke the current browser session when switching accounts.
    if old := request.cookies.get(COOKIE):
        session.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
    token, csrf = create_session(session, user)
    session.execute(delete(LoginAttempt).where(LoginAttempt.created_at < since))
    session.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=43200,
        path="/",
    )
    return {"user": public_user(user), "csrf_token": csrf}


@router.get("/me")
def me(user: Actor):
    return public_user(user)


class ProfileUpdate(Input):
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value is None:
            raise ValueError("이메일을 입력해 주세요.")
        return validate_email(value)

    major: str | None = Field(default=None, max_length=100)
    student_number: str | None = Field(default=None, max_length=40)
    avatar: str | None = Field(default=None, max_length=2800000)


@router.patch("/me/profile")
def update_profile(body: ProfileUpdate, session: Db, user: Actor):
    if "email" in body.model_fields_set:
        user.email = body.email
    if "major" in body.model_fields_set:
        user.major = body.major or None
    if "student_number" in body.model_fields_set:
        user.student_number = body.student_number or None
    if "avatar" in body.model_fields_set:
        if not body.avatar:
            user.avatar = None
        else:
            try:
                prefix, encoded = body.avatar.split(",", 1)
                if prefix not in ("data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"):
                    raise ValueError()
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError()
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.width * image.height > 16000000:
                            raise ValueError()
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        image = ImageOps.fit(image, (256, 256))
                        output = io.BytesIO()
                        image.save(output, format="JPEG", quality=85)
                user.avatar = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
            except Exception:
                deny(422, "2MB 이하의 JPG, PNG, WebP 사진을 선택해 주세요.")
    session.commit()
    return public_user(user)


@router.get("/auth/csrf")
def csrf(request: Request, user: Actor):
    return {"csrf_token": digest("csrf:" + request.cookies[COOKIE])}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: Db, user: Actor):
    session.delete(request.state.login)
    session.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/change-password", status_code=204)
def change_password(body: ChangePassword, session: Db, user: Actor, response: Response):
    try:
        hasher.verify(user.password_hash, body.current_password)
    except VerificationError:
        deny(400, "현재 비밀번호를 확인해 주세요.")
    user.password_hash = hasher.hash(body.new_password)
    user.must_change_password = False
    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    session.add(AuditEvent(actor_id=user.id, action="password_changed", target_id=user.id))
    session.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/reset-password", status_code=204)
def reset_password(body: ResetPassword, session: Db):
    token = session.scalar(
        select(ResetToken)
        .where(
            ResetToken.token_hash == digest(body.one_time_token),
            ResetToken.used.is_(False),
            ResetToken.expires_at > now(),
        )
        .with_for_update()
    )
    if not token:
        deny(400, "사용할 수 없는 초기화 토큰입니다.")
    user = session.get(User, token.user_id)
    user.password_hash = hasher.hash(body.new_password)
    user.must_change_password = False
    token.used = True
    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    session.commit()


class Provision(Input):
    login_id: str = Field(pattern=r"^[a-z0-9_.@-]{3,100}$")
    display_name: str = Field(min_length=1, max_length=100)


@router.post("/ops/teachers", status_code=201)
def provision(body: Provision, session: Db, actor: Actor):
    if actor.role != "operator":
        deny()
    user = User(
        login_id=body.login_id,
        display_name=body.display_name,
        role="teacher",
        password_hash=hasher.hash(secrets.token_urlsafe(32)),
        must_change_password=True,
    )
    session.add(user)
    session.flush()
    token = secrets.token_urlsafe(32)
    session.add(
        ResetToken(
            user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(hours=24)
        )
    )
    session.add(AuditEvent(actor_id=actor.id, action="teacher_provisioned", target_id=user.id))
    session.commit()
    return {"user": public_user(user), "one_time_token": token, "expires_in_hours": 24}


class Reason(Input):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/ops/users/{user_id}/reset-token")
def issue_reset(user_id: str, body: Reason, session: Db, actor: Actor):
    if actor.role != "operator":
        deny()
    if not session.get(User, user_id):
        deny(404)
    session.execute(delete(ResetToken).where(ResetToken.user_id == user_id))
    token = secrets.token_urlsafe(32)
    session.add(
        ResetToken(user_id=user_id, token_hash=digest(token), expires_at=now() + timedelta(hours=1))
    )
    session.add(
        AuditEvent(
            actor_id=actor.id,
            action="password_reset_issued",
            target_id=user_id,
            detail={"reason": body.reason},
        )
    )
    session.commit()
    return {"one_time_token": token, "expires_in_hours": 1}
