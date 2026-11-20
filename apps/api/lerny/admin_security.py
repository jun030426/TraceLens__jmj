"""Application administrator MFA. Secrets stay encrypted and proofs bind to a session."""

import secrets
import time
from datetime import timedelta

import pyotp
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import Request
from sqlalchemy import func, select

from lerny.admin_models import AdminGrant, AdminProof
from lerny.config import settings
from lerny.models import AuditEvent, LoginAttempt, now
from lerny.security import deny, digest, hasher


def audit(session, actor, action, target="operations", **detail):
    session.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            action="admin." + action,
            target_id=target,
            detail=detail,
        )
    )


def reject(session, actor, action, message, status=403, target="operations"):
    audit(session, actor, action, target, outcome="denied")
    session.commit()
    deny(status, message)


def grant_for(session, actor, *, lock=False):
    if actor.role != "operator":
        reject(session, actor, "access", "관리자 권한이 필요합니다.")
    query = select(AdminGrant).where(AdminGrant.user_id == actor.id)
    grant = session.scalar(query.with_for_update() if lock else query)
    # Existing operators retain their limited operational role, never ownership.
    if grant is None:
        from sqlalchemy.dialects.postgresql import insert

        session.execute(
            insert(AdminGrant)
            .values(
                user_id=actor.id,
                level="operator",
                last_counter=-1,
                recovery_hashes=[],
                created_at=now(),
            )
            .on_conflict_do_nothing()
        )
        grant = session.scalar(query.with_for_update())
    if grant.level not in {"owner", "operator"}:
        reject(session, actor, "access", "관리자 권한이 회수됐습니다.")
    return grant


def require_admin(session, actor, request: Request, *, owner=False, proof=True):
    grant = grant_for(session, actor)
    if owner and grant.level != "owner":
        reject(session, actor, "owner_access", "최고 관리자만 사용할 수 있어요.")
    verified = session.get(AdminProof, request.state.login.id)
    if proof and (not grant.mfa_secret or not verified or verified.expires_at <= now()):
        reject(session, actor, "mfa_required", "관리자 보안 인증을 완료해 주세요.")
    return grant


def cipher():
    key = settings().admin_mfa_key.get_secret_value()
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        deny(503, "관리자 보안 키 설정이 필요합니다.")


def password_check(session, actor, password):
    key = digest("admin-auth:" + actor.id)
    count = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.key == key, LoginAttempt.created_at > now() - timedelta(minutes=15))
    )
    if count >= 5:
        reject(
            session,
            actor,
            "security_rate_limited",
            "인증 시도가 많아요. 15분 후 다시 시도해 주세요.",
            429,
        )
    session.add(LoginAttempt(key=key))
    # A concurrent attacker cannot bypass the limit: callers lock the grant first.
    try:
        hasher.verify(actor.password_hash, password)
    except VerificationError:
        reject(session, actor, "security_failed", "비밀번호 또는 인증 코드를 확인해 주세요.", 401)


def verify_code(grant, code, secret):
    totp = pyotp.TOTP(secret)
    current = int(time.time()) // 30
    for counter in (current - 1, current, current + 1):
        if counter > grant.last_counter and secrets.compare_digest(totp.at(counter * 30), code):
            grant.last_counter = counter
            return True
    return False


def prove(session, request):
    row = session.get(AdminProof, request.state.login.id)
    expires = now() + timedelta(minutes=15)
    if row:
        row.expires_at = expires
    else:
        session.add(AdminProof(session_id=request.state.login.id, expires_at=expires))
    return expires
