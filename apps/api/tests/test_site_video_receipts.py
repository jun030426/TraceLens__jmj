from datetime import timedelta

import httpx
import pytest
from lerny import course_videos, video_worker
from lerny.heygen_slides import compile_studio
from lerny.models import ConceptVideo, Job, now
from test_gemini_integration import api, configured, integration  # noqa: F401
from test_weekly_publication import start
from test_weekly_publication import weekly as weekly_fixture

weekly = weekly_fixture


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    monkeypatch.setattr(video_worker.settings(), 'heygen_rendering_enabled', True)
    def forbidden(*args, **kwargs):
        raise AssertionError("Live network must not be used")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def row_in(weekly, status="queued", receipt=None):
    client, session, _ = weekly
    gid = start(client)
    row = ConceptVideo(course_id="course", generation_id=gid, version_id="version",
        concept_id="concept_stack", owner_id="teacher", position=1, title="스택", status=status,
        request=compile_studio("스택", ["card"], ["스택은 후입선출입니다."]),
        provider_video_id=receipt)
    session.add(row)
    session.commit()
    return client, session, row


def test_claim_persists_direct_receipt_and_restarts_only_poll(weekly, monkeypatch):
    _, session, row = row_in(weekly)
    monkeypatch.setattr(video_worker, "engine", lambda: session.bind)
    item = video_worker.claim(session)
    assert item["action"] == "submit"
    calls = []
    def provider(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(200, json={"data": {"video_id": "accepted"}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process(item, client)
    session.expire_all()
    assert row.provider_video_id == "accepted" and row.provider_session_id is None
    assert row.request["scenes"][0]["input"]["engine"]["type"] == "avatar_v"
    row.next_poll_at = now() - timedelta(seconds=1)
    session.commit()
    assert video_worker.claim(session)["action"] == "poll"
    assert calls == [("POST", "/v3/videos")]


def test_accepted_video_cannot_be_overwritten_by_draft_replay(weekly):
    _, session, row = row_in(weekly, status="ready", receipt="accepted")
    row.script = {"original": True}
    row.object_key = "old-video.mp4"
    original_request = row.request.copy()
    course_videos.accept_draft(session, Job(payload={"video_id": row.id}),
        {"validation": "model_reviewed", "draft": {"lesson": {"title": "replacement"}}})
    assert row.script == {"original": True}
    assert row.object_key == "old-video.mp4" and row.status == "ready"
    assert row.request == original_request


@pytest.mark.parametrize("status", ["needs_attention", "held", "storing"])
def test_teacher_retry_with_direct_receipt_only_resumes_poll(weekly, status):
    client, session, row = row_in(weekly, status=status, receipt="accepted")
    response = client.post(f"/api/v1/courses/course/concept-videos/{row.id}/retry")
    assert response.status_code == 200, response.text
    session.expire_all()
    assert row.status == "processing" and row.provider_video_id == "accepted"


def test_unknown_submission_receipt_remains_non_retryable(weekly):
    client, _, row = row_in(weekly, status="needs_attention")
    response = client.post(f"/api/v1/courses/course/concept-videos/{row.id}/retry")
    assert response.status_code == 409


def test_expired_submitting_with_receipt_recovers_as_poll(weekly):
    _, session, row = row_in(weekly, status="submitting", receipt="accepted")
    row.lease_until = now() - timedelta(seconds=1)
    session.commit()
    assert video_worker.claim(session)["action"] == "poll"


def test_credit_failure_stops_new_submissions_but_keeps_existing_receipt(weekly, monkeypatch):
    _, session, row = row_in(weekly, status='processing', receipt='credit-failed')
    monkeypatch.setattr(video_worker, 'engine', lambda: session.bind)
    item = video_worker.claim(session)
    def provider(req):
        assert req.method == 'GET'
        return httpx.Response(200, json={'data': {'status': 'failed',
            'failure_code': 'MOVIO_PAYMENT_INSUFFICIENT_CREDIT',
            'failure_message': "Insufficient credit. This operation requires 'api' credits."}})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        video_worker.process(item, client)
    session.expire_all()
    assert row.provider_video_id == 'credit-failed' and row.error_code == 'HEYGEN_API_CREDITS_REQUIRED'
    from lerny.models import Concept
    session.add(Concept(id='concept_other',course_id=row.course_id,name='other'));session.flush()
    other = ConceptVideo(course_id=row.course_id, generation_id=row.generation_id, version_id=row.version_id,
        concept_id='concept_other', owner_id=row.owner_id,position=2,title='대기',status='queued',request=row.request)
    session.add(other);session.commit()
    assert video_worker.claim(session) is None
    assert course_videos.view(session, other, True)['status'] == 'waiting_credits'
    # Already accepted jobs must still be polled during the credit hold.
    other.provider_video_id = 'already-accepted';other.status = 'processing';session.commit()
    assert video_worker.claim(session)['action'] == 'poll'


def test_explicit_credit_retry_preserves_receipt_in_audit_and_reuses_script(weekly):
    from sqlalchemy import select
    from lerny.models import AuditEvent
    client, session, row = row_in(weekly, status='failed', receipt='credit-failed')
    row.error_code = 'HEYGEN_API_CREDITS_REQUIRED'
    row.script = {'validated': True}
    job = Job(course_id='course',owner_id='teacher',kind='narration_lesson',status='succeeded',payload={})
    session.add(job);session.flush();row.script_job_id=job.id;session.commit()
    request = row.request.copy()
    result=client.post(f'/api/v1/courses/course/concept-videos/{row.id}/retry')
    assert result.status_code==200
    session.expire_all()
    assert row.status=='queued' and row.provider_video_id is None
    assert row.request==request and row.script=={'validated':True}
    event=session.scalar(select(AuditEvent).where(AuditEvent.action=='video_credit_failure_retried'))
    assert event.detail['previous_provider_video_id']=='credit-failed'


def test_ready_and_unknown_failure_cannot_be_regenerated(weekly):
    client, session, row = row_in(weekly, status='ready', receipt='completed')
    assert client.post(f'/api/v1/courses/course/concept-videos/{row.id}/retry').status_code==409
    row.status='failed';row.error_code='PROVIDER_TERMINAL_FAILURE';session.commit()
    assert client.post(f'/api/v1/courses/course/concept-videos/{row.id}/retry').status_code==409


@pytest.mark.parametrize("status,code",[(401,"HEYGEN_AUTH_REQUIRED"),(403,"HEYGEN_AUTH_REQUIRED"),(402,"HEYGEN_API_CREDITS_REQUIRED")])
def test_permanent_http_error_stops_polling_and_new_submission(weekly,monkeypatch,status,code):
    from lerny import operations, weekly_content
    _,session,row=row_in(weekly,status="processing",receipt="preserved-receipt")
    monkeypatch.setattr(video_worker,"engine",lambda:session.bind)
    monkeypatch.setattr(operations,"finished",lambda *a:None)
    calls=[]
    real_client=httpx.Client
    def provider(req):
        calls.append((req.method,req.url.path))
        return httpx.Response(status,json={"error":{"message":"must not persist provider details"}})
    monkeypatch.setattr(video_worker.httpx,"Client",lambda **kw:real_client(transport=httpx.MockTransport(provider),**kw))
    assert video_worker.run_once()
    session.expire_all()
    assert row.status=="held" and row.error_code==code and row.provider_video_id=="preserved-receipt"
    assert row.next_poll_at is None
    assert not video_worker.run_once() and len(calls)==1
    assert weekly_content.default_video_mode(session)=="none"


@pytest.mark.parametrize("status,body,expected",[
    (402,{},'HEYGEN_API_CREDITS_REQUIRED'),
    (400,{"error":{"code":"MOVIO_PAYMENT_INSUFFICIENT_CREDIT"}},'HEYGEN_API_CREDITS_REQUIRED'),
    (401,{},'HEYGEN_AUTH_REQUIRED'),
    (500,{},'SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT'),
])
def test_post_failure_never_auto_resubmits(weekly,monkeypatch,status,body,expected):
    _,session,row=row_in(weekly)
    monkeypatch.setattr(video_worker,"engine",lambda:session.bind)
    item=video_worker.claim(session)
    calls=[]
    with httpx.Client(transport=httpx.MockTransport(lambda req:
            (calls.append(req.method) or httpx.Response(status,json=body)))) as client:
        video_worker.process(item,client)
    session.expire_all()
    assert row.error_code==expected and row.provider_video_id is None
    assert video_worker.claim(session) is None
    assert calls==["POST"]


def test_missing_key_does_not_claim_or_call_provider(weekly,monkeypatch):
    from pydantic import SecretStr
    from lerny import operations,weekly_content
    _,session,row=row_in(weekly)
    monkeypatch.setattr(video_worker.settings(),"heygen_api_key",SecretStr(""))
    monkeypatch.setattr(operations,"finished",lambda *a:None)
    assert video_worker.claim(session) is None
    assert video_worker.run_once() is False
    assert weekly_content.default_video_mode(session)=="none"
    session.expire_all()
    assert row.status=="queued" and not row.provider_video_id


def test_cdn_permission_error_is_not_a_provider_authentication_failure():
    response=httpx.Response(403,request=httpx.Request("GET","https://media.example.test/video"))
    with pytest.raises(httpx.HTTPStatusError) as caught:response.raise_for_status()
    assert video_worker.permanent_provider_error(caught.value) is None


def test_provider_hold_resumes_only_on_explicit_teacher_action_with_configuration(weekly,monkeypatch):
    from lerny.models import AuditEvent
    from sqlalchemy import select
    from pydantic import SecretStr
    client,session,row=row_in(weekly,status='held')
    row.error_code='HEYGEN_AUTH_REQUIRED';session.commit()
    original=row.request.copy()
    monkeypatch.setattr(video_worker.settings(),'heygen_api_key',SecretStr(''))
    assert client.post(f'/api/v1/courses/course/concept-videos/{row.id}/retry').status_code==409
    session.expire_all();assert row.status=='held'
    monkeypatch.setattr(video_worker.settings(),'heygen_api_key',SecretStr('synthetic-test-key'))
    response=client.post(f'/api/v1/courses/course/concept-videos/{row.id}/retry')
    assert response.status_code==200,response.text
    session.expire_all()
    assert row.status=='queued' and row.error_code is None and row.request==original
    assert session.scalar(select(AuditEvent).where(AuditEvent.action=='video_provider_hold_retried'))
