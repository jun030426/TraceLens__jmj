"""Real local PostgreSQL + authenticated HTTP; cloud control is stubbed, never executed."""

from contextlib import nullcontext
from datetime import timedelta

import httpx
import pyotp
import pytest
from cryptography.fernet import Fernet
from lerny import admin_aws, admin_control, operations, worker
from lerny.admin_models import AdminGrant, AdminProof, OperationsWorker, ServerCommand
from lerny.config import settings
from lerny.models import AuditEvent, Job, LoginSession, User, now, uid
from pydantic import SecretStr
from sqlalchemy import select
from test_identity_courses import login, setup_course

PASSWORD = "Test-only-password-123"


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def authorize(db, name="operator1", level="owner"):
    user = db.scalar(select(User).where(User.login_id == name))
    grant = db.get(AdminGrant, user.id)
    if not grant:
        grant = AdminGrant(user_id=user.id)
        db.add(grant)
    grant.level, grant.mfa_secret = level, "test-encrypted-placeholder"
    login_session = db.scalar(select(LoginSession).where(LoginSession.user_id == user.id))
    proof = db.get(AdminProof, login_session.id)
    if proof:
        proof.expires_at = now() + timedelta(minutes=10)
    else:
        db.add(AdminProof(session_id=login_session.id, expires_at=now() + timedelta(minutes=10)))
    db.commit()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["student1", "teacher1"])
async def test_student_teacher_cannot_read_or_mutate_admin(app_db, name):
    app, db = app_db
    async with client(app) as c:
        await login(c, name)
        assert (await c.get("/api/v1/admin/users")).status_code == 403
        assert (
            await c.post(
                "/api/v1/admin/users",
                json={
                    "login_id": "new-admin-test",
                    "display_name": "new",
                    "role": "operator",
                    "reason": "test",
                },
            )
        ).status_code == 403
        assert db.scalar(select(User).where(User.login_id == "new-admin-test")) is None


@pytest.mark.asyncio
async def test_real_mfa_enrollment_proof_replay_and_recovery(app_db, monkeypatch):
    app, db = app_db
    monkeypatch.setattr(settings(), "admin_mfa_key", SecretStr(Fernet.generate_key().decode()))
    async with client(app) as c:
        await login(c, "operator1")
        assert (await c.get("/api/v1/admin/users")).status_code == 403
        start = await c.post("/api/v1/admin/security/enroll", json={"password": PASSWORD})
        assert start.status_code == 200, start.text
        secret = start.json()["secret"]
        user = db.scalar(select(User).where(User.login_id == "operator1"))
        grant = db.get(AdminGrant, user.id)
        assert grant.level == "operator" and secret not in grant.pending_secret
        code = pyotp.TOTP(secret).now()
        verified = await c.post(
            "/api/v1/admin/security/verify", json={"password": PASSWORD, "code": code}
        )
        assert verified.status_code == 200, verified.text
        recovery = verified.json()["recovery_codes"]
        assert len(recovery) == 8 and recovery[0] not in str(grant.recovery_hashes)
        assert (await c.get("/api/v1/admin/users")).status_code == 200
        assert (
            await c.post("/api/v1/admin/security/verify", json={"password": PASSWORD, "code": code})
        ).status_code == 401
        await login(c, "operator1")
        assert (
            await c.get("/api/v1/admin/users")
        ).status_code == 403  # proof not transferred to new session
        assert (
            await c.post(
                "/api/v1/admin/security/verify", json={"password": PASSWORD, "code": recovery[0]}
            )
        ).status_code == 200
        assert (
            await c.post(
                "/api/v1/admin/security/verify", json={"password": PASSWORD, "code": recovery[0]}
            )
        ).status_code == 401


@pytest.mark.asyncio
async def test_mfa_rate_limit(app_db, monkeypatch):
    app, _db = app_db
    monkeypatch.setattr(settings(), "admin_mfa_key", SecretStr(Fernet.generate_key().decode()))
    async with client(app) as c:
        await login(c, "operator1")
        for _ in range(5):
            assert (
                await c.post("/api/v1/admin/security/enroll", json={"password": "incorrect"})
            ).status_code == 401
        assert (
            await c.post("/api/v1/admin/security/enroll", json={"password": PASSWORD})
        ).status_code == 429


@pytest.mark.asyncio
async def test_suspend_revokes_student_session_and_keeps_records(app_db):
    app, db = app_db
    async with client(app) as admin, client(app) as student:
        await login(student, "student1")
        await login(admin, "operator1")
        authorize(db)
        target = db.scalar(select(User).where(User.login_id == "student1"))
        response = await admin.post(
            f"/api/v1/admin/users/{target.id}/actions",
            json={"action": "suspend", "reason": "운영 테스트"},
        )
        assert response.status_code == 200, response.text
        assert (await student.get("/api/v1/me")).status_code == 401
        assert db.get(User, target.id) and not target.active
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.user_suspend"))
        assert event.detail["before"]["active"] and not event.detail["after"]["active"]
        assert (
            await admin.post(
                f"/api/v1/admin/users/{target.id}/actions",
                json={"action": "activate", "reason": "운영 테스트"},
            )
        ).status_code == 200
        await login(student, "student1")


@pytest.mark.asyncio
async def test_operator_cannot_reset_owner_or_change_server_settings(app_db):
    app, db = app_db
    owner = User(
        login_id="real-owner", display_name="owner", role="operator", password_hash="unused"
    )
    db.add(owner)
    db.flush()
    db.add(AdminGrant(user_id=owner.id, level="owner"))
    db.commit()
    async with client(app) as c:
        await login(c, "operator1")
        authorize(db, level="operator")
        assert (
            await c.post(f"/api/v1/ops/users/{owner.id}/reset-token", json={"reason": "test"})
        ).status_code == 403
        assert (
            await c.post(
                f"/api/v1/admin/users/{owner.id}/actions",
                json={"action": "reset", "reason": "test"},
            )
        ).status_code == 403
        assert (
            await c.put(
                "/api/v1/admin/settings",
                json={
                    "revision": 1,
                    "maintenance": True,
                    "message": "점검 중",
                    "features": {key: True for key in operations.FEATURES},
                    "reason": "test",
                },
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_remove_self_and_revocation_is_immediate(app_db):
    app, db = app_db
    async with client(app) as c:
        await login(c, "operator1")
        user = authorize(db)
        assert (
            await c.post(
                f"/api/v1/admin/users/{user.id}/actions",
                json={"action": "suspend", "reason": "test"},
            )
        ).status_code == 409
        db.get(AdminGrant, user.id).level = "revoked"
        db.commit()
        assert (await c.get("/api/v1/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_user_list_never_returns_password_or_mfa_secrets(app_db):
    app, db = app_db
    async with client(app) as c:
        await login(c, "operator1")
        authorize(db)
        response = await c.get("/api/v1/admin/users?q=student&role=student")
        assert response.status_code == 200 and response.json()["total"] == 2
        for key in ("password_hash", "mfa_secret", "recovery_hashes", "token_hash"):
            assert key not in response.text
        created = await c.post(
            "/api/v1/admin/users",
            json={
                "login_id": "new-teacher",
                "display_name": "교수",
                "role": "teacher",
                "reason": "신규 강의",
            },
        )
        assert created.status_code == 201 and created.json()["one_time_token"]
        assert created.json()["user"]["must_change_password"]


@pytest.mark.asyncio
async def test_maintenance_blocks_learning_mutations_but_allows_admin_and_read(app_db):
    app, db = app_db
    async with client(app) as c:
        await login(c, "operator1")
        authorize(db)
        body = {
            "revision": 1,
            "maintenance": True,
            "message": "예정된 점검입니다",
            "features": {key: True for key in operations.FEATURES},
            "reason": "정기 점검",
        }
        assert (await c.put("/api/v1/admin/settings", json=body)).status_code == 200
        assert (await c.put("/api/v1/admin/settings", json=body)).status_code == 409
        assert (await c.get("/api/v1/admin/overview")).status_code == 200
        await login(c, "teacher1")
        assert (await c.get("/api/v1/me")).status_code == 200
        assert (
            await c.post(
                "/api/v1/terms",
                json={"name": "term", "starts_on": "2026-01-01", "ends_on": "2099-01-01"},
            )
        ).status_code == 503
        assert (await c.get("/api/v1/service-status")).json()["message"] == "예정된 점검입니다"
        await login(c, "operator1")
        authorize(db)
        body.update(revision=2, maintenance=False)
        assert (await c.put("/api/v1/admin/settings", json=body)).status_code == 200
        await login(c, "teacher1")
        await setup_course(c)


@pytest.mark.asyncio
async def test_stopped_features_reject_api_calls_and_worker_claims(app_db, monkeypatch):
    app, db = app_db
    control = operations.state(db)
    control.features = {key: False for key in operations.FEATURES}
    db.commit()
    async with client(app) as c:
        await login(c, "student1")
        assert (
            await c.post(
                f"/api/v1/sections/{uid()}/chat/messages",
                json={"question": "자료 설명", "thread_id": uid()},
                headers={"Idempotency-Key": uid()},
            )
        ).status_code == 503
    monkeypatch.setattr(worker, "Session", lambda _: nullcontext(db))
    assert worker.run_once() is False
    assert db.scalar(select(OperationsWorker).where(OperationsWorker.kind == "material"))


@pytest.mark.asyncio
async def test_admin_cancels_queued_job_and_does_not_interrupt_running(app_db):
    app, db = app_db
    async with client(app) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        teacher = db.scalar(select(User).where(User.login_id == "teacher1"))
        job = Job(
            owner_id=teacher.id,
            course_id=course["id"],
            kind="questions",
            payload={},
            status="queued",
        )
        db.add(job)
        db.commit()
        await login(c, "operator1")
        authorize(db)
        url = f"/api/v1/admin/jobs/material/{job.id}/actions"
        assert (
            await c.post(url, json={"action": "cancel", "reason": "중복 요청"})
        ).status_code == 200
        job.status = "running"
        db.commit()
        assert (
            await c.post(url, json={"action": "cancel", "reason": "중복 요청"})
        ).status_code == 409
        assert job.status == "running"
        job.status = "failed"
        db.commit()
        assert (
            await c.post(url, json={"action": "retry", "reason": "일시 오류"})
        ).status_code == 200
        assert job.status == "queued"


def configured(monkeypatch):
    monkeypatch.setattr(settings(), "admin_server_enabled", True)
    monkeypatch.setattr(admin_aws, "describe", lambda: {"state": "running"})


@pytest.mark.asyncio
async def test_admin_service_retry_preserves_generation_and_exposes_safe_diagnostic(app_db):
    from lerny.gemini_failures import EXHAUSTED
    app, db = app_db
    async with client(app) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        teacher = db.scalar(select(User).where(User.login_id == "teacher1"))
        job = Job(owner_id=teacher.id, course_id=course['id'], kind='weekly_content',
            payload={'_ai_generation':3}, status='failed', error_code=EXHAUSTED,
            result={'provider_error':{'http_status':503, 'service_failures':5},
                    'media_progress':{'completed':80}})
        db.add(job);db.commit()
        await login(c, 'operator1');authorize(db)
        listing=await c.get('/api/v1/admin/jobs')
        row=next(x for x in listing.json()['items'] if x['id']==job.id)
        assert row['provider_error']['http_status']==503
        response=await c.post(f'/api/v1/admin/jobs/material/{job.id}/actions',json={'action':'retry','reason':'제공자 복구 후 이어서 처리'})
        assert response.status_code==200, response.text
        assert job.status=='queued' and job.payload['_ai_generation']==3
        assert job.payload['_gemini_retry_round']==1
        assert job.result['media_progress']['completed']==80


@pytest.mark.asyncio
async def test_server_requires_scheduler_owner_confirmation_and_idempotency(app_db, monkeypatch):
    app, db = app_db
    configured(monkeypatch)
    async with client(app) as c:
        await login(c, "operator1")
        authorize(db)
        body = {"action": "stop", "reason": "정기 점검", "confirmation": "Lerny"}
        headers = {"Idempotency-Key": uid()}
        assert (
            await c.post("/api/v1/admin/server/commands", json=body, headers=headers)
        ).status_code == 503
        operations.state(db).scheduler_seen_at = now()
        db.commit()
        first = await c.post("/api/v1/admin/server/commands", json=body, headers=headers)
        assert first.status_code == 202, first.text
        second = await c.post("/api/v1/admin/server/commands", json=body, headers=headers)
        assert second.json()["id"] == first.json()["id"]
        assert (
            await c.post(
                "/api/v1/admin/server/commands", json=body, headers={"Idempotency-Key": uid()}
            )
        ).status_code == 409
        assert operations.state(db).server_hold


def new_command(db, action="stop"):
    user = db.scalar(select(User).where(User.login_id == "operator1"))
    control = operations.state(db)
    control.server_hold = True
    row = ServerCommand(
        actor_id=user.id, action=action, reason="test", idempotency_key=uid(), status="queued"
    )
    db.add(row)
    db.commit()
    return row


def test_server_stop_drains_then_confirms_without_duplicate_call(app_db, monkeypatch):
    _, db = app_db
    configured(monkeypatch)
    row = new_command(db)
    busy = OperationsWorker(id="test-worker", kind="material", last_seen_at=now(), busy=True)
    db.add(busy)
    db.commit()
    calls = []
    monkeypatch.setattr(admin_aws, "stop", lambda: calls.append("stop") or "request-1")
    admin_control.advance(db)
    assert row.status == "draining" and not calls
    busy.busy = False
    db.commit()
    admin_control.advance(db)
    assert row.status == "stopping" and calls == ["stop"]
    admin_control.advance(db)
    assert calls == ["stop"]
    monkeypatch.setattr(admin_aws, "describe", lambda: {"state": "stopped"})
    admin_control.advance(db)
    assert row.status == "succeeded" and operations.state(db).server_hold


def test_server_start_works_while_worker_is_off_and_waits_for_readiness(app_db, monkeypatch):
    _, db = app_db
    configured(monkeypatch)
    row = new_command(db, "start")
    calls = []
    monkeypatch.setattr(admin_aws, "describe", lambda: {"state": "stopped"})
    monkeypatch.setattr(admin_aws, "start", lambda: calls.append("start") or "request-2")
    admin_control.advance(db)
    assert row.status == "starting" and calls == ["start"]
    monkeypatch.setattr(admin_aws, "describe", lambda: {"state": "running"})
    admin_control.advance(db)
    assert row.status == "starting" and operations.state(db).server_hold
    for kind in ("code", "material", "video"):
        db.add(OperationsWorker(id=kind, kind=kind, last_seen_at=now(), ready=True))
    db.commit()
    admin_control.advance(db)
    assert row.status == "succeeded" and not operations.state(db).server_hold


def test_ambiguous_aws_response_is_not_reissued(app_db, monkeypatch):
    from botocore.exceptions import ReadTimeoutError

    _, db = app_db
    configured(monkeypatch)
    row = new_command(db)
    calls = []

    def uncertain():
        calls.append("stop")
        raise ReadTimeoutError(endpoint_url="https://example.invalid")

    monkeypatch.setattr(admin_aws, "stop", uncertain)
    admin_control.advance(db)
    assert row.status == "uncertain" and calls == ["stop"]
    row.sent_at = now() - timedelta(minutes=2)
    db.commit()
    admin_control.advance(db)
    assert (
        row.status == "needs_attention" and calls == ["stop"] and operations.state(db).server_hold
    )


def test_ec2_adapter_targets_only_configured_instance(monkeypatch):
    import boto3
    from botocore.stub import Stubber

    ec2 = boto3.client(
        "ec2", region_name="ap-southeast-2", aws_access_key_id="test", aws_secret_access_key="test"
    )
    monkeypatch.setattr(admin_aws, "ec2", lambda: ec2)
    monkeypatch.setattr(settings(), "admin_instance_id", "i-0123456789abcdef0")
    with Stubber(ec2) as stub:
        stub.add_response(
            "stop_instances",
            {"StoppingInstances": [], "ResponseMetadata": {"RequestId": "r1"}},
            {"InstanceIds": ["i-0123456789abcdef0"], "Force": False},
        )
        assert admin_aws.stop() == "r1"
        stub.add_response(
            "start_instances",
            {"StartingInstances": [], "ResponseMetadata": {"RequestId": "r2"}},
            {"InstanceIds": ["i-0123456789abcdef0"]},
        )
        assert admin_aws.start() == "r2"
        stub.assert_no_pending_responses()


def test_readiness_requires_target_server_and_stop_retires_only_its_workers(app_db, monkeypatch):
    _, db = app_db
    configured(monkeypatch)
    monkeypatch.setattr(settings(), "admin_instance_id", "i-0123456789abcdef0")
    for kind in ("code", "material", "video"):
        db.add(OperationsWorker(id=kind, kind=kind, last_seen_at=now(), ready=True))
    db.commit()
    assert not operations.workers_ready(db)  # Other hosts / Vercel cannot claim EC2 readiness.
    for worker_row in db.scalars(select(OperationsWorker)):
        worker_row.server_id = settings().admin_instance_id
        worker_row.busy = True
    other = OperationsWorker(
        id="another-host", kind="material", server_id="i-99999999999999999", busy=True
    )
    db.add(other)
    db.commit()
    assert operations.workers_ready(db)
    command = new_command(db)
    monkeypatch.setattr(admin_aws, "describe", lambda: {"state": "stopped"})
    admin_control.advance(db)
    assert command.status == "succeeded" and other.busy
    assert not operations.workers_ready(db)
    assert not db.get(OperationsWorker, "code").busy


def test_oidc_request_context_precedes_rotating_file_without_cross_request_leak(
    tmp_path, monkeypatch
):
    token_file = tmp_path / "oidc-token"
    token_file.write_text("file-token-1", encoding="utf-8")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN_FILE", str(token_file))
    assert admin_aws.oidc_token() == "file-token-1"
    token_file.write_text("file-token-2", encoding="utf-8")
    assert admin_aws.oidc_token() == "file-token-2"
    token = admin_aws.request_token.set("request-token")
    try:
        assert admin_aws.oidc_token() == "request-token"
    finally:
        admin_aws.request_token.reset(token)
    assert admin_aws.oidc_token() == "file-token-2"


def test_lambda_bridge_uses_fresh_token_and_fixed_https_destination(monkeypatch):
    import httpx

    cfg = settings()
    monkeypatch.setattr(cfg, "admin_server_enabled", True)
    monkeypatch.setattr(cfg, "admin_instance_id", "i-0123456789abcdef0")
    monkeypatch.setattr(cfg, "admin_aws_account", "123456789012")
    monkeypatch.setattr(cfg, "admin_control_url", "https://abc.lambda-url.ap-southeast-2.on.aws/")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "test-token")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200, json={"request_id": "request-1"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(admin_aws.httpx, "post", post)
    assert admin_aws.stop() == "request-1"
    assert calls[0][1]["json"] == {"action": "stop"}
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[0][1]["follow_redirects"] is False
    monkeypatch.setattr(cfg, "admin_control_url", "https://attacker.invalid/")
    with pytest.raises(ValueError, match="INVALID_CONTROL_URL"):
        admin_aws.start()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_video_cancel_refuses_running_script_and_cancels_waiting_script(app_db):
    from lerny.models import Concept, ConceptVideo, Material, MaterialVersion

    app, db = app_db
    async with client(app) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        teacher = db.scalar(select(User).where(User.login_id == "teacher1"))
        material = Material(
            course_id=course["id"], title="Synthetic", kind="lecture", week=1, visibility="public"
        )
        concept = Concept(course_id=course["id"], name="Synthetic")
        script = Job(
            owner_id=teacher.id,
            course_id=course["id"],
            kind="narration_lesson",
            status="running",
            payload={},
        )
        db.add_all([material, concept, script])
        db.flush()
        version = MaterialVersion(
            material_id=material.id,
            version_no=1,
            filename="synthetic.txt",
            sha256="a" * 64,
            object_key="unused",
            status="ready",
        )
        db.add(version)
        db.flush()
        video = ConceptVideo(
            course_id=course["id"],
            version_id=version.id,
            concept_id=concept.id,
            owner_id=teacher.id,
            position=1,
            title="Synthetic",
            script_job_id=script.id,
            status="script_pending",
        )
        db.add(video)
        db.commit()
        await login(c, "operator1")
        authorize(db)
        listing = (await c.get("/api/v1/admin/jobs?category=video&group=waiting")).json()
        assert listing["total"] == 1 and listing["summary"]["waiting"] == 1
        assert listing["items"][0]["title"] == "Synthetic"
        assert listing["items"][0]["course_title"] == course["title"]
        url = f"/api/v1/admin/jobs/video/{video.id}/actions"
        payload = {"action": "cancel", "reason": "대본 처리 확인"}
        assert (await c.post(url, json=payload)).status_code == 409
        assert video.status == "script_pending" and script.status == "running"
        script.status = "waiting_ai"
        db.commit()
        assert (await c.post(url, json=payload)).status_code == 200
        assert video.status == "cancelled" and script.status == "cancelled"


@pytest.mark.asyncio
async def test_job_summary_sorting_filtering_and_pagination_are_global(app_db):
    app, db = app_db
    async with client(app) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        teacher = db.scalar(select(User).where(User.login_id == "teacher1"))
        created = now()
        records = [
            Job(
                owner_id=teacher.id,
                course_id=course["id"],
                kind="questions",
                payload={"private": "must-not-leak"},
                status="succeeded",
                created_at=created - timedelta(minutes=i),
            )
            for i in range(35)
        ]
        for i, status in enumerate(("running", "failed", "queued", "waiting_ai", "cancelled")):
            records.append(
                Job(
                    owner_id=teacher.id,
                    course_id=course["id"],
                    kind="chat",
                    payload={"private": "must-not-leak"},
                    status=status,
                    created_at=created - timedelta(days=5 - i),
                )
            )
        db.add_all(records)
        db.commit()
        await login(c, "operator1")
        authorize(db)
        response = await c.get("/api/v1/admin/jobs")
        assert response.status_code == 200
        result = response.json()
        assert result["summary"] == {
            "all": 40,
            "running": 1,
            "attention": 1,
            "waiting": 2,
            "done": 35,
            "cancelled": 1,
        }
        assert result["total"] == 40 and len(result["items"]) == 30
        assert [x["status"] for x in result["items"][:2]] == ["running", "failed"]
        assert result["items"][0]["course_title"] == course["title"]
        assert "must-not-leak" not in response.text and '"payload"' not in response.text
        second = (await c.get("/api/v1/admin/jobs?offset=30")).json()
        assert len(second["items"]) == 10
        assert not {x["id"] for x in result["items"]}.intersection(x["id"] for x in second["items"])
        waiting = (await c.get("/api/v1/admin/jobs?group=waiting")).json()
        assert waiting["total"] == 2 and waiting["summary"] == result["summary"]
        newest = (await c.get("/api/v1/admin/jobs?order=newest")).json()
        assert newest["items"][0]["status"] == "succeeded"
        oldest = (await c.get("/api/v1/admin/jobs?order=oldest")).json()
        assert oldest["items"][0]["status"] == "running"
        recent_response = await c.get("/api/v1/admin/jobs?days=1")
        assert recent_response.status_code == 200
        recent = recent_response.json()
        assert recent["summary"]["all"] == 35 and recent["summary"]["running"] == 0
        assert (await c.get("/api/v1/admin/jobs?days=2")).status_code == 422
        search = (await c.get("/api/v1/admin/jobs", params={"q": course["title"]})).json()
        assert search["total"] == 40
        assert (await c.get("/api/v1/admin/jobs", params={"q": "%"})).json()["total"] == 0
        assert (await c.get("/api/v1/admin/jobs?order=invalid")).status_code == 422


@pytest.mark.asyncio
async def test_code_job_context_and_lease_without_source_exposure(app_db):
    from lerny.models import CodeRun

    app, db = app_db
    async with client(app) as c:
        await login(c, "teacher1")
        course, section = await setup_course(c)
        teacher = db.scalar(select(User).where(User.login_id == "teacher1"))
        run = CodeRun(
            owner_id=teacher.id,
            section_id=section["id"],
            language="python",
            source="PRIVATE_STUDENT_CODE",
            result={"private": "OUTPUT"},
            status="running",
            lease_until=now() + timedelta(minutes=1),
            expires_at=now() + timedelta(minutes=5),
        )
        db.add(run)
        db.commit()
        await login(c, "operator1")
        authorize(db)
        response = await c.get("/api/v1/admin/jobs?category=code&group=running")
        assert response.status_code == 200
        result = response.json()
        assert result["total"] == 1 and result["summary"]["running"] == 1
        assert result["items"][0]["course_title"] == course["title"]
        assert result["items"][0]["locked"] is True
        assert '"source"' not in response.text and '"result"' not in response.text
        assert "PRIVATE_STUDENT_CODE" not in response.text
