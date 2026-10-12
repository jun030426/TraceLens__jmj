import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from lerny.db import db
from lerny.models import Course, CourseStaff, Enrollment, LoginSession, User, now

hasher = PasswordHasher()
Db = Annotated[Session, Depends(db)]
COOKIE = "lerny_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def deny(code=403, message="접근 권한이 없습니다."):
    raise HTTPException(code, detail=message)


def current_user(request: Request, session: Db) -> User:
    token = request.cookies.get(COOKIE, "")
    login = session.scalar(
        select(LoginSession).where(
            LoginSession.token_hash == digest(token), LoginSession.expires_at > now()
        )
    )
    if not login:
        deny(401, "로그인이 필요합니다.")
    user = session.get(User, login.user_id)
    if not user or not user.active:
        deny(401, "사용할 수 없는 계정입니다.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(login.csrf_hash, digest(csrf)):
            deny(403, "보안 토큰을 확인해 주세요.")
    if user.must_change_password and request.url.path not in (
        "/api/v1/me",
        "/api/v1/auth/csrf",
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
    ):
        deny(403, "초기 비밀번호를 먼저 변경해 주세요.")
    request.state.login = login
    return user


Actor = Annotated[User, Depends(current_user)]


def create_session(session: Session, user: User):
    token = secrets.token_urlsafe(32)
    csrf = digest("csrf:" + token)
    session.add(
        LoginSession(
            user_id=user.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=now() + timedelta(hours=12),
        )
    )
    return token, csrf


def staff_access(session: Session, user: User, course_id: str, permission="edit") -> Course:
    course = session.get(Course, course_id)
    if not course:
        deny(404, "과목을 찾을 수 없습니다.")
    if user.id == course.lead_teacher_id:
        return course
    staff = session.scalar(
        select(CourseStaff).where(
            CourseStaff.course_id == course_id,
            CourseStaff.teacher_id == user.id,
            CourseStaff.active.is_(True),
        )
    )
    if not staff:
        deny(404, "과목을 찾을 수 없습니다.")
    if permission == "edit" and not staff.can_edit:
        deny()
    if permission == "analyze" and not staff.can_analyze:
        deny()
    return course


def course_access(session: Session, user: User, course_id: str) -> Course:
    course = session.get(Course, course_id)
    if not course:
        deny(404, "과목을 찾을 수 없습니다.")
    if user.role == "student":
        enrolled = session.scalar(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == user.id,
                Enrollment.status == "active",
            )
        )
        if not enrolled:
            deny(404, "과목을 찾을 수 없습니다.")
        return course
    return staff_access(session, user, course_id, "read")


def match_revision(actual: int, expected: Annotated[str | None, Header()]):
    if expected is None:
        deny(428, "If-Match 버전이 필요합니다.")
    if expected.strip('"') != str(actual):
        deny(409, "다른 변경이 반영됐습니다. 새로고침해 주세요.")
