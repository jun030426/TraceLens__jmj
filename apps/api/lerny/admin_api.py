"""Administrative workflows, with explicit privileges and no arbitrary DB/OS console."""

import secrets
from datetime import timedelta
from typing import Literal

import pyotp
from fastapi import APIRouter, Header, Query, Request, Response
from lerny import admin_aws, admin_workers, operations
from lerny.admin_control import ACTIVE, command_view
from lerny.admin_models import AdminGrant, AdminProof, ServerCommand
from lerny.admin_security import (
    audit,
    cipher,
    grant_for,
    password_check,
    prove,
    reject,
    require_admin,
    verify_code,
)
from lerny.auth import Input
from lerny.config import settings
from lerny.models import (
    AuditEvent,
    CodeRun,
    ConceptVideo,
    Course,
    Job,
    LoginAttempt,
    LoginSession,
    Material,
    MaterialVersion,
    ModelCall,
    ResetToken,
    Section,
    User,
    now,
)
from lerny.security import Actor, Db, deny, digest, hasher
from pydantic import Field
from sqlalchemy import case, delete, func, or_, select

router = APIRouter(prefix="/api/v1")


class Reason(Input):
    reason: str = Field(min_length=3, max_length=500)


class Credentials(Input):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=80)


@router.get("/service-status")
def service_status(session: Db):
    return operations.public_state(operations.state(session))


@router.get("/admin/security")
def security_status(request: Request, session: Db, actor: Actor):
    grant = require_admin(session, actor, request, proof=False)
    proof = session.get(AdminProof, request.state.login.id)
    session.commit()
    return {
        "level": grant.level,
        "enrolled": bool(grant.mfa_secret),
        "verified": bool(proof and proof.expires_at > now()),
        "expires_at": proof.expires_at if proof else None,
        "configured": bool(settings().admin_mfa_key.get_secret_value()),
    }


@router.post("/admin/security/enroll")
def enroll(body: Credentials, request: Request, session: Db, actor: Actor):
    grant = grant_for(session, actor, lock=True)
    password_check(session, actor, body.password)
    if grant.mfa_secret:
        reject(
            session, actor, "mfa_enroll", "이미 등록되어 있어요. 인증 코드를 입력해 주세요.", 409
        )
    secret = pyotp.random_base32()
    grant.pending_secret = cipher().encrypt(secret.encode()).decode()
    grant.pending_until = now() + timedelta(minutes=10)
    audit(session, actor, "mfa_enroll_started", actor.id, outcome="succeeded")
    session.commit()
    return {
        "secret": secret,
        "uri": pyotp.TOTP(secret).provisioning_uri(name=actor.login_id, issuer_name="Lerny 관리자"),
        "expires_at": grant.pending_until,
    }


@router.post("/admin/security/verify")
def verify(body: Credentials, request: Request, session: Db, actor: Actor):
    grant = grant_for(session, actor, lock=True)
    password_check(session, actor, body.password)
    enrolling = not grant.mfa_secret
    encrypted = grant.mfa_secret or grant.pending_secret
    if not encrypted or (enrolling and (not grant.pending_until or grant.pending_until < now())):
        reject(session, actor, "mfa_verify", "인증 앱 등록을 먼저 진행해 주세요.", 409)
    valid = verify_code(grant, body.code, cipher().decrypt(encrypted.encode()).decode())
    if not valid and not enrolling:
        hashed = digest(body.code)
        if hashed in grant.recovery_hashes:
            grant.recovery_hashes = [value for value in grant.recovery_hashes if value != hashed]
            valid = True
    if not valid:
        reject(session, actor, "mfa_verify_failed", "비밀번호 또는 인증 코드를 확인해 주세요.", 401)
    recovery = []
    if enrolling:
        grant.mfa_secret, grant.pending_secret, grant.pending_until = encrypted, None, None
        recovery = [secrets.token_hex(8) for _ in range(8)]
        grant.recovery_hashes = [digest(value) for value in recovery]
    expires = prove(session, request)
    session.execute(
        delete(LoginAttempt).where(LoginAttempt.key == digest("admin-auth:" + actor.id))
    )
    audit(session, actor, "mfa_verified", actor.id, outcome="succeeded")
    session.commit()
    return {"verified": True, "expires_at": expires, "recovery_codes": recovery}


@router.get("/admin/overview")
def overview(request: Request, session: Db, actor: Actor, response: Response):
    grant = require_admin(session, actor, request)
    counts = {
        role: count
        for role, count in session.execute(select(User.role, func.count()).group_by(User.role))
    }
    jobs = {
        status: count
        for status, count in session.execute(select(Job.status, func.count()).group_by(Job.status))
    }
    control = operations.state(session)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "level": grant.level,
        "users": counts,
        "courses": session.scalar(select(func.count()).select_from(Course)),
        "jobs": jobs,
        **admin_workers.overview(session, control),
        "database": "ready",
        "checked_at": now(),
        "operations": operations.public_state(control),
        "busy": operations.busy_counts(session),
    }


@router.get("/admin/workers")
def worker_history(request: Request, session: Db, actor: Actor, response: Response,
                   kind: Literal["material", "code", "video", "interactive"] | None = None,
                   offset: int = Query(default=0, ge=0),
                   limit: int = Query(default=5, ge=1, le=20)):
    require_admin(session, actor, request)
    response.headers["Cache-Control"] = "private, no-store"
    return admin_workers.history(session, kind=kind, offset=offset, limit=limit)


def user_view(session, user):
    grant = session.get(AdminGrant, user.id)
    return {
        "id": user.id,
        "login_id": user.login_id,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "active": user.active,
        "admin_level": grant.level if grant else None,
        "created_at": user.created_at,
        "must_change_password": user.must_change_password,
    }


@router.get("/admin/users")
def users(
    request: Request, session: Db, actor: Actor, q: str = "", role: str = "", offset: int = 0
):
    require_admin(session, actor, request)
    query = select(User)
    if q:
        pattern = "%" + q[:100].replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                User.login_id.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )
    if role:
        query = query.where(User.role == role)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    return {
        "items": [
            user_view(session, row)
            for row in session.scalars(
                query.order_by(User.created_at.desc(), User.id).offset(max(0, offset)).limit(30)
            )
        ],
        "total": total,
    }


class CreateUser(Reason):
    login_id: str = Field(pattern=r"^[a-z0-9_.@-]{3,100}$")
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["teacher", "student", "operator"] = "teacher"


@router.post("/admin/users", status_code=201)
def create_user(body: CreateUser, request: Request, session: Db, actor: Actor):
    require_admin(session, actor, request, owner=body.role == "operator")
    if session.scalar(select(User.id).where(User.login_id == body.login_id)):
        reject(session, actor, "user_create", "이미 사용 중인 아이디입니다.", 409)
    user = User(
        login_id=body.login_id,
        display_name=body.display_name,
        role=body.role,
        password_hash=hasher.hash(secrets.token_urlsafe(32)),
        must_change_password=True,
    )
    session.add(user)
    session.flush()
    if body.role == "operator":
        session.add(AdminGrant(user_id=user.id, level="operator"))
    token = secrets.token_urlsafe(32)
    session.add(
        ResetToken(
            user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(hours=24)
        )
    )
    audit(
        session,
        actor,
        "user_created",
        user.id,
        outcome="succeeded",
        reason=body.reason,
        role=body.role,
    )
    session.commit()
    return {"user": user_view(session, user), "one_time_token": token, "expires_in_hours": 24}


def managed_user(session, actor, request, user_id):
    grant = require_admin(session, actor, request)
    operations.state(session, lock=True)  # Serializes ownership changes and last-owner checks.
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        deny(404, "계정을 찾을 수 없습니다.")
    target = session.get(AdminGrant, user.id)
    if user.role == "operator" and grant.level != "owner":
        reject(
            session,
            actor,
            "user_manage",
            "관리자 계정은 최고 관리자만 관리할 수 있어요.",
            target=user.id,
        )
    if user.id == actor.id:
        reject(
            session, actor, "user_manage", "본인 계정은 내 정보에서 변경해 주세요.", 409, user.id
        )
    if target and target.level == "owner":
        owners = session.scalar(
            select(func.count())
            .select_from(AdminGrant)
            .join(User)
            .where(AdminGrant.level == "owner", User.active.is_(True))
        )
        if owners <= 1:
            reject(
                session,
                actor,
                "user_manage",
                "마지막 최고 관리자는 변경할 수 없습니다.",
                409,
                user.id,
            )
    return user


class UserAction(Reason):
    action: Literal[
        "suspend", "activate", "logout", "reset", "grant_operator", "grant_owner", "revoke_admin"
    ]


@router.post("/admin/users/{user_id}/actions")
def user_action(user_id: str, body: UserAction, request: Request, session: Db, actor: Actor):
    user = managed_user(session, actor, request, user_id)
    target_grant = session.get(AdminGrant, user.id)
    before = {
        "active": user.active,
        "role": user.role,
        "admin_level": target_grant.level if target_grant else None,
    }
    token = None
    if body.action in {"grant_owner", "grant_operator", "revoke_admin"}:
        require_admin(session, actor, request, owner=True)
        # Preserve student/teacher course semantics; only a dedicated operator account can change admin level.
        if user.role != "operator":
            reject(
                session,
                actor,
                "role_change",
                "전용 운영자 계정을 발급한 뒤 권한을 지정해 주세요.",
                409,
                user.id,
            )
        grant = session.get(AdminGrant, user.id)
        if not grant:
            grant = AdminGrant(user_id=user.id)
            session.add(grant)
        grant.level = {
            "grant_owner": "owner",
            "grant_operator": "operator",
            "revoke_admin": "revoked",
        }[body.action]
    elif body.action in {"suspend", "activate"}:
        user.active = body.action == "activate"
    elif body.action == "reset":
        session.execute(delete(ResetToken).where(ResetToken.user_id == user.id))
        token = secrets.token_urlsafe(32)
        session.add(
            ResetToken(
                user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(hours=1)
            )
        )
        user.must_change_password = True
    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    target_grant = session.get(AdminGrant, user.id)
    audit(
        session,
        actor,
        "user_" + body.action,
        user.id,
        reason=body.reason,
        outcome="succeeded",
        before=before,
        after={
            "active": user.active,
            "role": user.role,
            "admin_level": target_grant.level if target_grant else None,
        },
    )
    session.commit()
    return {
        "user": user_view(session, user),
        "one_time_token": token,
        "expires_in_hours": 1 if token else None,
    }


JOB_GROUPS = {
    "running": ("running", "submitting", "processing", "storing"),
    "waiting": ("queued", "waiting_ai", "script_pending", "pending"),
    "attention": ("failed", "held", "needs_attention"),
    "done": ("succeeded", "ready"),
    "cancelled": ("cancelled", "revoked"),
}


def job_group(status):
    return next((name for name, values in JOB_GROUPS.items() if status in values), "attention")


@router.get("/admin/jobs")
def list_jobs(
    request: Request,
    session: Db,
    actor: Actor,
    category: Literal["material", "code", "video"] = "material",
    status: str = "",
    offset: int = 0,
    group: Literal["all", "running", "waiting", "attention", "done", "cancelled"] = "all",
    order: Literal["priority", "newest", "oldest"] = "priority",
    q: str = "",
    days: int = 0,
):
    require_admin(session, actor, request)
    if days not in {0, 1, 7, 30}:
        deny(422, "조회 기간이 올바르지 않습니다.")
    model = {"material": Job, "code": CodeRun, "video": ConceptVideo}[category]
    query = select(model, User.login_id, User.display_name, Course.title).outerjoin(
        User, User.id == model.owner_id
    )
    if category == "code":
        query = query.outerjoin(Section, Section.id == CodeRun.section_id).outerjoin(
            Course, Course.id == Section.course_id
        )
    else:
        query = query.outerjoin(Course, Course.id == model.course_id)
    if q.strip():
        term = (
            "%"
            + q.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        label = {"material": Job.kind, "code": CodeRun.language, "video": ConceptVideo.title}[
            category
        ]
        query = query.where(
            or_(
                *(
                    column.ilike(term, escape="\\")
                    for column in (
                        User.login_id,
                        User.display_name,
                        Course.title,
                        label,
                    )
                )
            )
        )
    if days:
        query = query.where(model.created_at >= now() - timedelta(days=days))
    # Summary covers the entire searched period, not just the visible page or selected status.
    base = query.subquery()
    counts = dict(
        session.execute(select(base.c.status, func.count()).group_by(base.c.status)).all()
    )
    summary = {name: 0 for name in JOB_GROUPS}
    for value, count in counts.items():
        summary[job_group(value)] += count
    summary["all"] = sum(counts.values())
    group_expression = case(
        *((model.status.in_(values), name) for name, values in JOB_GROUPS.items()),
        else_="attention",
    )
    if group != "all":
        query = query.where(group_expression == group)
    if status:
        query = query.where(model.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    if order == "priority":
        priority = case(
            *(
                (group_expression == name, i)
                for i, name in enumerate(("running", "attention", "waiting", "done", "cancelled"))
            ),
            else_=5,
        )
        ordering = (priority, model.created_at.desc(), model.id)
    else:
        ordering = (
            model.created_at.asc() if order == "oldest" else model.created_at.desc(),
            model.id,
        )
    items = []
    checked_at = now()
    for row, owner_login, owner_name, course_title in session.execute(
        query.order_by(*ordering).offset(max(0, offset)).limit(30)
    ):
        items.append(
            {
                "id": row.id,
                "kind": getattr(row, "kind", category),
                "status": row.status,
                "owner": owner_login or "삭제된 계정",
                "owner_name": owner_name or "삭제된 계정",
                "course_title": course_title or "강의 정보 없음",
                "group": job_group(row.status),
                "locked": bool(row.lease_until and row.lease_until > checked_at),
                "error_code": row.error_code,
                "provider_error": (row.result or {}).get("provider_error") if category == "material" else None,
                "created_at": row.created_at,
                "attempt": getattr(row, "attempt", None),
                "provider_submitted": bool(getattr(row, "provider_session_id", None)
                                           or getattr(row, "provider_video_id", None)),
                "title": getattr(row, "title", ""),
            }
        )
    return {"items": items, "total": total, "summary": summary, "checked_at": checked_at}


class JobAction(Reason):
    action: Literal["retry", "cancel"]


@router.post("/admin/jobs/{category}/{job_id}/actions")
def job_action(
    category: Literal["material", "code", "video"],
    job_id: str,
    body: JobAction,
    request: Request,
    session: Db,
    actor: Actor,
):
    require_admin(session, actor, request)
    control = operations.state(session, lock=True)
    model = {"material": Job, "code": CodeRun, "video": ConceptVideo}[category]
    row = session.scalar(select(model).where(model.id == job_id).with_for_update())
    if not row:
        deny(404, "작업을 찾을 수 없습니다.")
    before = row.status
    if row.status in {"running", "submitting"} or (row.lease_until and row.lease_until > now()):
        reject(
            session, actor, "job_action", "실행 중인 작업은 완료 후 관리할 수 있어요.", 409, row.id
        )
    if body.action == "cancel":
        script = None
        if category == "video" and row.script_job_id:
            script = session.scalar(
                select(Job).where(Job.id == row.script_job_id).with_for_update(skip_locked=True)
            )
            if (
                not script
                or script.status == "running"
                or (script.lease_until and script.lease_until > now())
                or session.scalar(
                    select(ModelCall.id)
                    .where(ModelCall.job_id == row.script_job_id, ModelCall.status == "running")
                    .limit(1)
                )
            ):
                reject(
                    session,
                    actor,
                    "job_cancel",
                    "영상 대본 작업이 실행 중이에요. 완료 후 다시 확인해 주세요.",
                    409,
                    row.id,
                )
        if category == "material" and session.scalar(
            select(ModelCall.id)
            .where(ModelCall.job_id == row.id, ModelCall.status == "running")
            .limit(1)
        ):
            reject(
                session,
                actor,
                "job_cancel",
                "외부 AI 요청이 실행 중이에요. 완료 후 다시 확인해 주세요.",
                409,
                row.id,
            )
        if row.status not in {"queued", "waiting_ai", "script_pending"} or (
            category == "video" and (row.provider_session_id or row.provider_video_id)
        ):
            reject(
                session,
                actor,
                "job_cancel",
                "현재 상태에서는 안전하게 취소할 수 없어요.",
                409,
                row.id,
            )
        row.status = "cancelled"
        if category == "material":
            session.execute(
                delete(ModelCall).where(ModelCall.job_id == row.id, ModelCall.status == "queued")
            )
            update_attempt(session, row, "held")
        if script and script.status in {"queued", "waiting_ai"}:
            script.status = "cancelled"
            session.execute(
                delete(ModelCall).where(ModelCall.job_id == script.id, ModelCall.status == "queued")
            )
    else:
        feature = (
            operations.JOB_FEATURE.get(getattr(row, "kind", ""), "content")
            if category == "material"
            else ("grading" if category == "code" else "videos")
        )
        if not operations.enabled(control, feature):
            reject(
                session,
                actor,
                "job_retry",
                "점검 또는 기능 중지를 해제한 뒤 재시도해 주세요.",
                409,
                row.id,
            )
        if category == "code":
            reject(
                session,
                actor,
                "job_retry",
                "실행 후 코드는 보관하지 않아요. 학생이 다시 제출해야 합니다.",
                409,
                row.id,
            )
        if category == "video":
            from lerny.course_videos import current_source

            if not current_source(session, row):
                reject(session, actor, "job_retry", "원본 자료가 변경되었어요.", 409, row.id)
            if (row.provider_session_id or row.provider_video_id) and row.status in {
                "processing",
                "storing",
                "held",
                "needs_attention",
            }:
                row.status, row.next_poll_at, row.error_code = "processing", now(), None
            else:
                reject(
                    session,
                    actor,
                    "job_retry",
                    "외부 접수 여부 확인이 필요해요. 자동 재생성을 제한합니다.",
                    409,
                    row.id,
                )
        else:
            from lerny.security import course_access

            owner = session.get(User, row.owner_id)
            if not owner or not owner.active:
                reject(
                    session, actor, "job_retry", "작업 소유 계정이 비활성 상태입니다.", 409, row.id
                )
            course_access(session, owner, row.course_id)
            if row.status != "failed" or row.kind in {
                "lecture_spec",
                "lecture_grounding",
                "narration_lesson",
            }:
                reject(
                    session,
                    actor,
                    "job_retry",
                    "전용 재생성 경로 또는 원본 확인이 필요한 작업입니다.",
                    409,
                    row.id,
                )
            from lerny.gemini_failures import prepare_retry
            prepare_retry(row, session)
            row.status, row.error_code = "queued", None
            row.lease_token, row.lease_until = None, None
            if row.kind in {"extract", "embed"}:
                version = session.get(MaterialVersion, row.payload["version_id"])
                material = session.get(Material, version.material_id)
                if material.deleted:
                    session.rollback()
                    reject(
                        session,
                        actor,
                        "job_retry",
                        "삭제된 자료는 다시 처리할 수 없어요.",
                        409,
                        job_id,
                    )
                version.status = "extracted" if row.kind == "embed" else "queued"
                version.error_code = None
            update_attempt(session, row, "pending")
    audit(
        session,
        actor,
        "job_" + body.action,
        row.id,
        category=category,
        reason=body.reason,
        outcome="succeeded",
        before=before,
        after=row.status,
    )
    session.commit()
    return {"status": row.status}


def update_attempt(session, job, status):
    from lerny.models import PracticeAttempt, grading_attempt

    if job.kind == "grade":
        attempt = grading_attempt(session, job)
    elif job.kind == "practice_grade":
        attempt = session.get(PracticeAttempt, job.payload["attempt_id"])
    else:
        return
    if status == "pending" and attempt.status != "held":
        deny(409, "이미 처리된 답안은 다시 채점할 수 없어요.")
    attempt.status = status
    if status == "held":
        attempt.feedback = {
            "message": "운영자가 채점 요청을 취소하여 검토 보류했어요. 오답으로 처리하지 않아요."
        }


@router.get("/admin/settings")
def get_settings(request: Request, session: Db, actor: Actor):
    require_admin(session, actor, request)
    row = operations.state(session)
    return {
        **operations.public_state(row),
        "features": {key: row.features.get(key, True) for key in operations.FEATURES},
        "message": row.message,
    }


class SettingsChange(Reason):
    revision: int = Field(ge=1)
    maintenance: bool
    message: str = Field(min_length=1, max_length=500)
    features: dict[str, bool]


@router.put("/admin/settings")
def put_settings(body: SettingsChange, request: Request, session: Db, actor: Actor):
    require_admin(session, actor, request, owner=True)
    row = operations.state(session, lock=True)
    if row.revision != body.revision:
        reject(
            session,
            actor,
            "settings_update",
            "다른 변경이 반영됐어요. 새로고침 후 다시 시도해 주세요.",
            409,
        )
    if set(body.features) != set(operations.FEATURES):
        deny(422, "기능 설정을 확인해 주세요.")
    before = {"maintenance": row.maintenance, "features": row.features, "message": row.message}
    row.maintenance, row.features, row.message = body.maintenance, body.features, body.message
    row.revision += 1
    audit(
        session,
        actor,
        "settings_updated",
        reason=body.reason,
        outcome="succeeded",
        before=before,
        after={"maintenance": row.maintenance, "features": row.features, "message": row.message},
    )
    session.commit()
    return {"revision": row.revision}


@router.get("/admin/server")
def server(request: Request, session: Db, actor: Actor):
    require_admin(session, actor, request)
    configured = settings().admin_server_enabled
    observed = {"state": "not_configured"}
    if configured:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            observed = admin_aws.describe()
        except (BotoCoreError, ClientError, ValueError, KeyError, IndexError):
            observed = {"state": "unavailable"}
    row = operations.state(session)
    commands = list(
        session.scalars(select(ServerCommand).order_by(ServerCommand.created_at.desc()).limit(10))
    )
    return {
        **observed,
        "configured": configured,
        "busy": operations.busy_counts(session),
        "server_hold": row.server_hold,
        "scheduler_seen_at": row.scheduler_seen_at,
        "scheduler_ready": bool(
            row.scheduler_seen_at and row.scheduler_seen_at > now() - timedelta(minutes=3)
        ),
        "commands": [command_view(command) for command in commands],
        "checked_at": now(),
    }


class ServerAction(Reason):
    action: Literal["start", "stop", "restart", "resume"]
    confirmation: str


@router.post("/admin/server/commands", status_code=202)
def server_command(
    body: ServerAction,
    request: Request,
    session: Db,
    actor: Actor,
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    require_admin(session, actor, request, owner=True)
    row = operations.state(session, lock=True)
    existing = session.scalar(
        select(ServerCommand).where(ServerCommand.idempotency_key == idempotency_key)
    )
    if existing:
        if (
            existing.actor_id != actor.id
            or existing.action != body.action
            or existing.reason != body.reason
        ):
            deny(409, "요청 식별자가 다른 작업에 사용됐습니다.")
        return command_view(existing)
    if not settings().admin_server_enabled:
        reject(session, actor, "server_request", "AWS 제어 연결 설정이 필요합니다.", 503)
    if body.confirmation != "Lerny":
        deny(422, "확인란에 Lerny를 입력해 주세요.")
    if not row.scheduler_seen_at or row.scheduler_seen_at < now() - timedelta(minutes=3):
        reject(
            session, actor, "server_request", "독립 실행 스케줄러의 연결을 먼저 확인해 주세요.", 503
        )
    if session.scalar(select(ServerCommand.id).where(ServerCommand.status.in_(ACTIVE)).limit(1)):
        reject(session, actor, "server_request", "기존 서버 작업이 진행 중이에요.", 409)
    if body.action == "resume":
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            observed = admin_aws.describe()["state"]
        except (BotoCoreError, ClientError, ValueError, KeyError, IndexError):
            reject(session, actor, "server_resume", "AWS 연결 상태를 확인해 주세요.", 503)
        if observed != "running" or not operations.workers_ready(session):
            reject(
                session,
                actor,
                "server_resume",
                "서버와 모든 작업 처리기의 정상 상태를 먼저 확인해 주세요.",
                409,
            )
        row.server_hold = False
        audit(session, actor, "server_resumed", reason=body.reason, outcome="succeeded")
        session.commit()
        return {"status": "succeeded"}
    row.server_hold = True
    command = ServerCommand(
        actor_id=actor.id,
        action=body.action,
        reason=body.reason,
        idempotency_key=idempotency_key,
        status="queued",
    )
    session.add(command)
    session.flush()
    audit(
        session,
        actor,
        "server_requested",
        command.id,
        operation=body.action,
        reason=body.reason,
        outcome="accepted",
    )
    session.commit()
    return command_view(command)


@router.get("/admin/audit")
def audit_log(request: Request, session: Db, actor: Actor, offset: int = 0):
    require_admin(session, actor, request)
    query = select(AuditEvent).where(AuditEvent.action.like("admin.%"))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = []
    for item in session.scalars(
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset(max(0, offset)).limit(30)
    ):
        user = session.get(User, item.actor_id) if item.actor_id else None
        rows.append(
            {
                "id": item.id,
                "actor": user.login_id if user else "시스템",
                "action": item.action,
                "target_id": item.target_id,
                "detail": item.detail,
                "created_at": item.created_at,
            }
        )
    return {"items": rows, "total": total}
