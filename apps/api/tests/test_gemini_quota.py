"""No external requests: simulated time plus real isolated DB admission/worker replay."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from lerny import gemini_provider as provider, gemini_quota as quota
from lerny.config import Settings
from lerny.inference import job_context
from lerny.models import GeminiQuota, Job
from test_gemini_integration import configured, integration, api  # noqa: F401

PATH = "interactions"
BODY = {"model": "gemini-3.5-flash-lite", "input": "synthetic"}


@pytest.fixture
def paced(tmp_path, monkeypatch):
    db = create_engine('sqlite:///' + str(tmp_path / 'quota.db'))
    GeminiQuota.__table__.create(db)
    config = Settings(runtime_root=tmp_path, ai_provider="gemini", gemini_calls_enabled=True,
                      gemini_api_key=SecretStr("synthetic-key"))
    clock = [1794373200.0]
    monkeypatch.setattr(quota, 'engine', lambda: db)
    monkeypatch.setattr(quota, 'settings', lambda: config)
    monkeypatch.setattr(provider, 'settings', lambda: config)
    monkeypatch.setattr(quota, 'db_time', lambda session: clock[0])
    monkeypatch.setattr(quota.time, 'time', lambda: clock[0])
    yield config, clock, db
    db.dispose()


def pending(code, fn):
    with pytest.raises(quota.ProviderDeferred, match=code) as error:
        fn()
    return error.value.retry_at


def test_shared_gap_survives_changed_worker_directory_and_api_key(paced, tmp_path):
    config, clock, db = paced
    first = quota.reserve_slot(PATH, BODY)
    quota.release_slot(first)
    config.runtime_root = tmp_path / 'another-host'
    config.gemini_api_key = SecretStr('rotated-test-key')
    assert pending('GEMINI_PACING_WAIT', lambda: quota.reserve_slot(PATH, BODY)) == clock[0] + 5
    clock[0] += 5
    second = quota.reserve_slot(PATH, BODY)
    assert first[0] == second[0] and first[1] != second[1]
    # A stale worker cannot release the new lease.
    quota.release_slot(first)
    pending('GEMINI_PACING_WAIT', lambda: quota.reserve_slot(PATH, BODY))
    with Session(db) as session:
        row = session.get(GeminiQuota, first[0])
        assert row.day_count == 2
        assert 'synthetic' not in json.dumps(row.recent)


def test_live_request_serializes_calls_and_abandoned_lease_expires(paced):
    _, clock, _ = paced
    lease = quota.reserve_slot(PATH, BODY)
    clock[0] += 10
    pending('GEMINI_PACING_WAIT', lambda: quota.reserve_slot(PATH, BODY))
    clock[0] += 291
    assert quota.reserve_slot(PATH, BODY)[1] != lease[1]


def test_embedding_and_content_have_independent_limits(paced):
    content = quota.reserve_slot(PATH, BODY)
    embedding = quota.reserve_slot('models/gemini-embedding-2:embedContent', {'content': 'synthetic'})
    assert embedding[0] != content[0]
    assert quota.scope(PATH, {'model': 'gemini-3.5-flash'}) == quota.scope(PATH, {'model': 'gemini-3.6-flash'})


def test_paid_verification_keeps_completed_responses_and_free_project_backoff(paced, monkeypatch):
    config, clock, _ = paced
    config.gemini_review_quota_project = "paid-test"
    config.gemini_review_course_id = "course"
    config.gemini_review_week = 4
    config.gemini_embedding_api_key = SecretStr("paid-test-key")
    headers = []
    def post(_client, _url, **kwargs):
        headers.append(kwargs["headers"]["x-goog-api-key"])
        return httpx.Response(200, json={"ok":True}, request=httpx.Request("POST", "https://test.invalid"))
    monkeypatch.setattr(httpx.Client, "post", post)
    job = SimpleNamespace(id="test-route", kind="questions", course_id="course", payload={"generation_id":"test"})
    generation = SimpleNamespace(week=4, course_id="course")
    with job_context(job), quota.review_job(SimpleNamespace(scalar=lambda _: generation), job, config):
        provider.request(PATH, BODY, dict)
        quota.block_until(PATH, BODY, "GEMINI_RATE_LIMITED", clock[0] + 3600)
        changed = {**BODY, "input":"second synthetic request"}
        with quota.verification():
            provider.request(PATH, BODY, dict)
            provider.request(PATH, changed, dict)
            assert quota.request_purpose("models/test:embedContent", config) == "embedding"
            config.gemini_embedding_api_key = SecretStr("")
            with pytest.raises(ValueError, match="GEMINI_KEY_REQUIRED"):
                provider.request(PATH, {**BODY,"input":"unavailable"}, dict)
        with pytest.raises(quota.ProviderDeferred, match="GEMINI_RATE_LIMITED"):
            provider.request(PATH, {**BODY,"input":"free"}, dict)
    assert headers == ["synthetic-key","paid-test-key"]


@pytest.mark.parametrize("kind,course,week,gen,expected", [
    ("weekly_content", "course", 4, "selected", "draft"),
    ("questions", "course", 4, "selected", "draft"),
    ("practice_prepare", "course", 4, "selected", "draft"),
    ("weekly_content", "other", 4, "selected", "content"),
    ("weekly_content", "course", 5, "selected", "content"),
    ("weekly_content", "course", 4, "different", "content"),
    ("weekly_content", "course", None, "selected", "content"),
    ("narration_lesson", "course", 4, "selected", "content"),
    ("grade", "course", 4, "selected", "content"),
])
def test_paid_generation_is_bound_to_one_draft(paced, monkeypatch, kind, course, week, gen, expected):
    config, _, _ = paced
    config.gemini_review_course_id = "course"
    config.gemini_review_week = 4
    config.gemini_review_quota_project = "paid-test"
    config.gemini_paid_generation_id = "selected"
    config.gemini_embedding_api_key = SecretStr("paid-test-key")
    job = SimpleNamespace(id="job", kind=kind, course_id=course, payload={"generation_id":gen, "week":4})
    sent = []
    def post(_client, _url, **kwargs):
        sent.append(kwargs["headers"]["x-goog-api-key"])
        return httpx.Response(200, json={"ok":True}, request=httpx.Request("POST", "https://test.invalid"))
    monkeypatch.setattr(httpx.Client, "post", post)
    free_scope = quota.scope(PATH, BODY)
    generation = SimpleNamespace(week=week, course_id=course) if week is not None else None
    with job_context(job), quota.review_job(SimpleNamespace(scalar=lambda _: generation), job, config):
        assert quota.request_purpose(PATH, config) == expected
        assert (quota.scope(PATH, BODY) != free_scope) == (expected == "draft")
        assert quota.request_purpose("models/test:embedContent", config) == "embedding"
        provider.request(PATH, BODY, dict)
        if kind == "questions":
            with quota.verification():
                assert quota.request_purpose(PATH, config) == "review"
    assert sent == ["paid-test-key" if expected == "draft" else "synthetic-key"]
    assert quota.request_purpose(PATH, config) == "content"


def test_minute_budget_includes_every_call_and_no_boundary_burst(paced):
    _, clock, _ = paced
    start = clock[0]
    for i in range(12):
        clock[0] = start + i * 5
        quota.release_slot(quota.reserve_slot(PATH, BODY))
    clock[0] = start + 59.99
    assert pending('GEMINI_PACING_WAIT', lambda: quota.reserve_slot(PATH, BODY)) >= start + 60
    clock[0] = start + 60.01
    quota.release_slot(quota.reserve_slot(PATH, BODY))


def test_token_budget_waits_for_old_input_to_expire(paced):
    config, clock, _ = paced
    size = len(json.dumps(BODY, ensure_ascii=False).encode())
    config.gemini_content_tokens_per_minute = size + 1
    quota.release_slot(quota.reserve_slot(PATH, BODY))
    clock[0] += 5
    assert pending('GEMINI_PACING_WAIT', lambda: quota.reserve_slot(PATH, BODY)) > clock[0] + 54
    with pytest.raises(ValueError, match='GEMINI_INPUT_BUDGET_EXCEEDED'):
        quota.reserve_slot(PATH, {**BODY, 'input': 'x' * 1000})
    clock[0] += 56
    quota.release_slot(quota.reserve_slot(PATH, BODY))


def test_configured_daily_limit_resets_in_pacific_time(paced):
    config, clock, _ = paced
    config.gemini_content_requests_per_day = 1
    quota.release_slot(quota.reserve_slot(PATH, BODY))
    deadline = pending('GEMINI_DAILY_WAIT', lambda: quota.reserve_slot(PATH, BODY))
    assert deadline == quota.next_day(clock[0])
    clock[0] = deadline
    quota.release_slot(quota.reserve_slot(PATH, BODY))


@pytest.mark.parametrize('date,hours', [('2026-03-08T00:00:00', 23), ('2026-11-01T00:00:00', 25)])
def test_daily_reset_tracks_daylight_saving(date, hours):
    start = datetime.fromisoformat(date).replace(tzinfo=quota.PACIFIC).timestamp()
    assert quota.next_day(start) - start == hours * 3600 + 1


def fake_http(monkeypatch, response):
    calls = []
    real = httpx.Client
    def transport(request):
        calls.append(request)
        return response
    monkeypatch.setattr(provider.httpx, 'Client', lambda **kwargs: real(transport=httpx.MockTransport(transport), **kwargs))
    return calls


def test_pacing_does_not_send_or_poison_response_cache(paced, monkeypatch):
    config, clock, db = paced
    calls = fake_http(monkeypatch, httpx.Response(200, json={'result': 'ok'}))
    with job_context(SimpleNamespace(id='job-a', payload={})):
        assert provider.request(PATH, BODY, lambda x: x) == {'result': 'ok'}
        # Cached response never consumes a new slot, even while blocked.
        assert provider.request(PATH, BODY, lambda x: x) == {'result': 'ok'}
    with job_context(SimpleNamespace(id='job-b', payload={})):
        pending('GEMINI_PACING_WAIT', lambda: provider.request(PATH, BODY, lambda x: x))
        assert len(calls) == 1
        clock[0] += 5
        assert provider.request(PATH, BODY, lambda x: x) == {'result': 'ok'}
    assert len(calls) == 2
    with Session(db) as session:
        assert session.scalar(select(GeminiQuota.day_count)) == 2


def test_provider_quota_blocks_other_hosts_using_retryinfo(paced, monkeypatch, tmp_path):
    config, clock, _ = paced
    calls = fake_http(monkeypatch, httpx.Response(429, json={'error': {'details': [{'retryDelay': '90s'}]}}))
    with job_context(SimpleNamespace(id='job-a', payload={})):
        assert pending('GEMINI_RATE_LIMITED', lambda: provider.request(PATH, BODY, lambda x: x)) == clock[0] + 90
    # No shared local files: another host still sees the DB cooldown.
    config.runtime_root = tmp_path / 'another-host'
    with job_context(SimpleNamespace(id='job-b', payload={})):
        assert pending('GEMINI_RATE_LIMITED', lambda: provider.request(PATH, BODY, lambda x: x)) == clock[0] + 90
    assert len(calls) == 1


def test_daily_error_without_header_waits_until_reset(paced):
    _, clock, _ = paced
    response = httpx.Response(429, json={'error': {'details': [{'violations': [{
        'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}})
    assert provider.provider_deadline(response, 'GEMINI_RATE_LIMITED') == quota.next_day(clock[0])


def test_database_outage_never_falls_back_to_unpaced_http(paced, monkeypatch):
    _, _, db = paced
    GeminiQuota.__table__.drop(db)
    calls = fake_http(monkeypatch, httpx.Response(200, json={}))
    with job_context(SimpleNamespace(id='no-db', payload={})):
        pending('GEMINI_QUOTA_UNAVAILABLE', lambda: provider.request(PATH, BODY, lambda x: x))
    assert calls == []


@pytest.mark.parametrize('code', ['GEMINI_PACING_WAIT', 'GEMINI_DAILY_WAIT', 'GEMINI_QUOTA_UNAVAILABLE'])
def test_worker_yields_without_exhausting_retries_then_completes(integration, monkeypatch, code):
    from lerny import weekly_content as automatic, worker
    from lerny.models import now
    _, session, _ = integration
    monkeypatch.setattr(worker, 'heartbeat', lambda *args: None)
    def defer(*args):
        raise quota.ProviderDeferred(code, now().timestamp() + 5)
    monkeypatch.setattr(automatic, 'generate_job', defer)
    job = Job(owner_id='teacher', course_id='course', kind='weekly_content', payload={}, attempt=2)
    session.add(job); session.commit()
    for _ in range(12):
        assert worker.run_once(job.id)
        session.expire_all()
        assert job.status == 'queued' and job.attempt == 2
        assert worker.run_once(job.id) is False
        job.lease_until = None
        session.commit()
    monkeypatch.setattr(automatic, 'generate_job', lambda *args: {'count': 4})
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == 'succeeded' and job.result == {'count': 4}


def test_postgres_concurrent_admission_is_atomic(monkeypatch):
    url = os.environ.get('LERNY_INGESTION_TEST_URL')
    if not url:
        pytest.skip('Run with disposable localhost PostgreSQL runner')
    db = create_engine(url)
    assert db.url.host in {'127.0.0.1', 'localhost', '::1'}
    GeminiQuota.__table__.create(db, checkfirst=True)
    config = Settings(gemini_quota_project='concurrency-test')
    monkeypatch.setattr(quota, 'engine', lambda: db)
    monkeypatch.setattr(quota, 'settings', lambda: config)
    def request(_):
        try:
            return quota.reserve_slot(PATH, BODY)
        except quota.ProviderDeferred:
            return None
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            leases = list(pool.map(request, range(16)))
        assert sum(x is not None for x in leases) == 1
        with Session(db) as session:
            assert session.scalar(select(GeminiQuota.day_count)) == 1
    finally:
        GeminiQuota.__table__.drop(db)
        db.dispose()


def test_old_upload_work_is_not_starved_by_new_daily_jobs(integration, monkeypatch):
    from datetime import timedelta
    from lerny import weekly_content as automatic, personalized, worker
    from lerny.models import now
    _, session, _ = integration
    monkeypatch.setattr(worker, 'heartbeat', lambda *args: None)
    monkeypatch.setattr(automatic, 'generate_job', lambda *args: {'stage': 'concepts'})
    monkeypatch.setattr(personalized, 'generate_daily', lambda *args: {'stage': 'daily'})
    old = Job(owner_id='teacher', course_id='course', kind='weekly_content', payload={},
              created_at=now() - timedelta(minutes=1))
    new = Job(owner_id='teacher', course_id='course', kind='daily_theory', payload={})
    session.add_all([old, new]); session.commit()
    assert worker.run_once()
    session.expire_all()
    assert old.status == 'succeeded' and new.status == 'queued'


def test_multicall_job_resumes_from_cached_step_without_duplicate_generation(integration, monkeypatch):
    from lerny import weekly_content as automatic, worker
    from lerny.models import now
    _, session, _ = integration
    clock = [now().timestamp()]
    monkeypatch.setattr(quota, 'engine', lambda: session.bind)
    monkeypatch.setattr(quota, 'db_time', lambda s: clock[0])
    monkeypatch.setattr(provider, 'reserve_slot', quota.reserve_slot)
    monkeypatch.setattr(provider, 'release_slot', quota.release_slot)
    monkeypatch.setattr(provider, 'block_until', quota.block_until)
    monkeypatch.setattr(worker, 'heartbeat', lambda *args: None)
    calls = fake_http(monkeypatch, httpx.Response(200, json={'result': 'ok'}))
    def steps(*args):
        first = provider.request(PATH, {**BODY, 'input': 'step-one'}, lambda x: x)
        second = provider.request(PATH, {**BODY, 'input': 'step-two'}, lambda x: x)
        return {'first': first, 'second': second}
    monkeypatch.setattr(automatic, 'generate_job', steps)
    job = Job(owner_id='teacher', course_id='course', kind='weekly_content', payload={})
    session.add(job); session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == 'queued' and job.error_code == 'GEMINI_PACING_WAIT'
    assert job.attempt == 0 and len(calls) == 1
    clock[0] += 5.01
    job.lease_until = None; session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == 'succeeded' and job.result['second'] == {'result': 'ok'}
    assert len(calls) == 2 and session.scalar(select(GeminiQuota.day_count)) == 2


def test_worker_records_error_then_stops_service_retry_without_replacing_progress(integration, monkeypatch):
    from lerny import weekly_content, worker, gemini_failures
    from lerny.models import now
    _, session, _ = integration
    monkeypatch.setattr(worker, 'heartbeat', lambda *args: None)
    detail = {'http_status':503, 'service_failures':5}
    monkeypatch.setattr(gemini_failures, 'latest_error', lambda job: detail)
    def stopped(*args):
        raise ValueError(gemini_failures.EXHAUSTED)
    monkeypatch.setattr(weekly_content, 'generate_job', stopped)
    job = Job(owner_id='teacher', course_id='course', kind='weekly_content', payload={},
              result={'media_progress':{'completed':80}})
    session.add(job);session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == 'failed' and job.error_code == gemini_failures.EXHAUSTED
    assert job.lease_until is None
    assert job.result['media_progress']['completed'] == 80
    assert job.result['provider_error'] == detail
    assert not worker.run_once(job.id)
