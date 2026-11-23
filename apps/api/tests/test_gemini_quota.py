"""No external requests: simulated time plus real isolated DB admission/worker replay."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
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


@pytest.mark.parametrize("override,review_gap", [(None, 5), (60, 1)])
def test_review_only_rpm_and_embedding_project_accounting(paced, override, review_gap):
    import hashlib
    config, clock, db = paced
    config.gemini_review_quota_project = "lerny-paid-embedding"
    config.gemini_review_requests_per_minute = override
    config.gemini_embedding_requests_per_minute = 120
    embed_path = "models/gemini-embedding-2:embedContent"

    def reserve(path, payload, project, model, gap):
        lease = quota.reserve_slot(path, payload)
        expected = hashlib.sha256(json.dumps([project, model]).encode()).hexdigest()
        assert lease[0] == expected
        with Session(db) as session:
            assert session.get(GeminiQuota, expected).next_at == clock[0] + gap
        quota.release_slot(lease)

    reserve(PATH, BODY, "lerny", BODY["model"], 5)
    # The base deployment labels physical embedding calls with the default
    # quota project. Its model gives it a distinct row from paid review.
    reserve(embed_path, {}, "lerny", "gemini-embedding-2", .5)
    token = quota._paid_job.set(True)
    try:
        with quota.verification():
            reserve(PATH, BODY, "lerny-paid-embedding", BODY["model"], review_gap)
    finally:
        quota._paid_job.reset(token)


def test_review_slots_keep_rolling_limits_and_expire_independently(paced, monkeypatch):
    config, clock, db = paced
    config.gemini_review_quota_project = "test-paid"
    config.gemini_review_requests_per_minute = 4
    config.gemini_review_concurrency = 4
    config.gemini_content_requests_per_day = 5
    monkeypatch.setattr(quota, "request_purpose", lambda *_: "review")
    leases = []
    for _ in range(4):
        leases.append(quota.reserve_slot(PATH, BODY))
        if len(leases) < 4:
            pending("GEMINI_PACING_WAIT", lambda: quota.reserve_slot(PATH, BODY))
            clock[0] += 15
    clock[0] += 15.02
    pending("GEMINI_PACING_WAIT", lambda: quota.reserve_slot(PATH, BODY))
    quota.release_slot(leases[1])
    extra = quota.reserve_slot(PATH, BODY)
    quota.release_slot(leases[1])
    with Session(db) as session:
        assert set(session.get(GeminiQuota, extra[0]).active_leases) == {lease[1] for lease in (leases[0], *leases[2:], extra)}
    pending("GEMINI_DAILY_WAIT", lambda: quota.reserve_slot(PATH, BODY))
    config.gemini_content_requests_per_day = 0
    clock[0] += 241
    quota.reserve_slot(PATH, BODY)
    with Session(db) as session:
        keys = session.get(GeminiQuota, extra[0]).active_leases
        assert leases[0][1] not in keys and leases[2][1] in keys


def test_parallel_paid_requests_still_obey_tpm(paced, monkeypatch):
    config, clock, _ = paced
    monkeypatch.setattr(quota, "request_purpose", lambda *_: "review")
    from lerny.gemini_input import input_units
    config.gemini_review_concurrency = 4
    config.gemini_review_requests_per_minute = 60
    config.gemini_content_tokens_per_minute = input_units(BODY)
    quota.reserve_slot(PATH, BODY)
    clock[0] += 1
    assert pending("GEMINI_PACING_WAIT", lambda: quota.reserve_slot(PATH, BODY)) >= clock[0]+59


@pytest.mark.parametrize("override", [None, 5])
def test_paid_gateway_counts_combined_admissions_and_deduplicates(paced, monkeypatch, override):
    import threading
    import time
    from lerny.config import PaidCallBudget
    from lerny.models import GeminiPaidCallBudget

    config, _, db = paced
    GeminiPaidCallBudget.__table__.create(db)
    config.gemini_default_paid_call_budget = 5 if override is None else 1
    if override is not None:
        config.gemini_paid_call_budget = PaidCallBudget(version_id="target", max_new_calls=override)
    config.gemini_review_concurrency = 4
    config.gemini_review_requests_per_minute = config.gemini_embedding_requests_per_minute = 6000
    config.gemini_review_quota_project = "paid"
    config.gemini_embedding_api_key = SecretStr("synthetic")
    tick = iter(range(1800000000,1800005000))
    monkeypatch.setattr(quota, "db_time", lambda session: next(tick))
    for module in (provider, quota):
        monkeypatch.setattr(module, "request_purpose", lambda path, _: "review" if path == PATH else "embedding")

    calls = []
    lock = threading.Lock()
    live = [0, 0]
    def post(_client, path, **kwargs):
        with lock:
            calls.append(kwargs["json"]["input"])
            live[0] += 1
            live[1] = max(live)
        try:
            time.sleep(.15)
            return httpx.Response(200, json={"ok":True}, request=httpx.Request("POST","https://fixture.invalid"))
        finally:
            with lock:
                live[0] -= 1
    monkeypatch.setattr(httpx.Client, "post", post)
    def send(value, embed=False):
        with job_context(SimpleNamespace(id="embed" if embed else "review", payload={"version_id":"target"})):
            path = "models/gemini-embedding-2:embedContent" if embed else PATH
            return provider.request(path, {**BODY, "input": value}, dict)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(send, value) for value in ("a","a","b","c","d")]
        assert all(f.result() == {"ok":True} for f in futures)
    assert sorted(calls) == ["a","b","c","d"] and 1 < live[1] <= 4
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, "r"), pool.submit(send, "e", True)]
        assert sum(f.exception() is None for f in futures) == 1
        assert [str(f.exception()) for f in futures if f.exception()] == ["GEMINI_PAID_CALL_BUDGET_EXCEEDED"]
    assert len(calls) == 5 and send("a") == {"ok":True}
    with Session(db) as session:
        total = session.get(GeminiPaidCallBudget, "target")
        assert total.review + total.embedding == 5
    events = list((config.runtime_root/"gemini-calls").glob("*/attempts/*.json"))
    assert len(events) == 5


def test_postgres_parallel_paid_admissions_and_late_release(monkeypatch):
    from threading import Barrier
    from sqlalchemy.engine import make_url
    from lerny.config import PaidCallBudget
    from lerny.models import GeminiPaidCallBudget

    url = os.environ.get("LERNY_INGESTION_TEST_URL")
    if not url:
        pytest.skip("Requires disposable loopback PostgreSQL")
    assert make_url(url).host in {"127.0.0.1","::1","localhost"}
    db = create_engine(url)
    tables = [GeminiQuota.__table__, GeminiPaidCallBudget.__table__]
    for table in tables:
        table.create(db)
    config = Settings(gemini_review_quota_project="paid-parallel", gemini_review_concurrency=4,
                      gemini_review_requests_per_minute=60,
                      gemini_paid_call_budget=PaidCallBudget(version_id="target", max_new_calls=5))
    ticks = iter(range(1800000000,1800001000))
    monkeypatch.setattr(quota, "engine", lambda: db)
    monkeypatch.setattr(quota, "settings", lambda: config)
    monkeypatch.setattr(quota, "db_time", lambda _: next(ticks))
    monkeypatch.setattr(quota,"request_purpose",lambda path,_: "review" if path == PATH else "embedding")
    barrier = Barrier(8)
    def admit(_):
        with job_context(SimpleNamespace(id="review", payload={"version_id":"target"})):
            barrier.wait(timeout=10)
            try:
                return quota.reserve_slot(PATH, BODY)
            except quota.ProviderDeferred:
                return None
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            live = [lease for lease in pool.map(admit, range(8)) if lease]
        assert len(live) == 4
        with job_context(SimpleNamespace(id="embed",payload={"version_id":"target"})):
            quota.reserve_slot("models/embed:embedContent", {"input":"x"})
        quota.release_slot(live[0])
        with job_context(SimpleNamespace(id="review",payload={"version_id":"target"})):
            with pytest.raises(ValueError,match="GEMINI_PAID_CALL_BUDGET_EXCEEDED"):
                quota.reserve_slot(PATH, BODY)
        with Session(db) as s:
            row=s.get(GeminiQuota,live[0][0])
            budget=s.get(GeminiPaidCallBudget,"target")
            assert len(row.active_leases)==3 and row.day_count==4
            assert (budget.review,budget.embedding)==(4,1)
    finally:
        for table in reversed(tables):
            table.drop(db)
        db.dispose()


def test_default_budget_reuses_existing_rows_and_exempts_unbound_requests(paced, monkeypatch):
    from lerny.config import PaidCallBudget
    from lerny.models import GeminiPaidCallBudget

    config, clock, db = paced
    GeminiPaidCallBudget.__table__.create(db)
    config.gemini_paid_call_budget = PaidCallBudget(version_id="lower", max_new_calls=235)
    monkeypatch.setattr(quota, "request_purpose", lambda *args: "embedding")
    assert config.gemini_default_paid_call_budget == 1500
    with Session(db) as session:
        session.add_all([GeminiPaidCallBudget(version_id="lower", review=149, embedding=86),
                         GeminiPaidCallBudget(version_id="default", review=762, embedding=95)])
        session.commit()

    def admit(version):
        clock[0] += 61
        with job_context(SimpleNamespace(id="synthetic", payload={"version_id": version})):
            quota.release_slot(quota.reserve_slot("models/test:embedContent", BODY))

    with pytest.raises(ValueError, match="GEMINI_PAID_CALL_BUDGET_EXCEEDED"):
        admit("lower")
    admit("default")
    config.gemini_default_paid_call_budget = 858
    with pytest.raises(ValueError, match="GEMINI_PAID_CALL_BUDGET_EXCEEDED"):
        admit("default")
    admit(None)
    monkeypatch.setattr(quota, "request_purpose", lambda *_: "content")
    clock[0] += 61
    with job_context(SimpleNamespace(id="free-content", payload={"version_id": "lower"})):
        quota.release_slot(quota.reserve_slot(PATH, BODY))
    with Session(db) as session:
        rows = session.scalars(select(GeminiPaidCallBudget)).all()
        assert {r.version_id: (r.review, r.embedding) for r in rows} == {
            "lower": (149, 86), "default": (762, 96)}


def test_embedding_worker_retries_only_missing_vectors_after_budget_raise(integration, configured, monkeypatch):
    from lerny import worker
    from lerny.models import GeminiPaidCallBudget
    from test_gemini_integration import VECTOR

    client, session, _ = integration
    monkeypatch.setattr(configured, "gemini_default_paid_call_budget", 1)
    monkeypatch.setattr(quota, "engine", lambda: session.bind)
    monkeypatch.setattr(provider, "reserve_slot", quota.reserve_slot)
    monkeypatch.setattr(provider, "release_slot", quota.release_slot)
    monkeypatch.setattr(worker, "heartbeat", lambda *_: None)
    ticks = iter(range(1800000000, 1800001000, 61))
    monkeypatch.setattr(quota, "db_time", lambda _: next(ticks))
    calls = fake_http(monkeypatch, httpx.Response(200, json={"embedding": {"values": VECTOR}}))
    job = Job(owner_id="teacher", course_id="course", kind="embed", payload={"version_id": "version"})
    session.add(job)
    session.commit()
    for attempt in range(2):
        if attempt:
            assert client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 202
        assert worker.run_once(job.id)
        session.expire_all()
        assert job.status == "failed" and job.error_code == "GEMINI_PAID_CALL_BUDGET_EXCEEDED"
        assert job.lease_until is None and not worker.run_once(job.id)
        assert "_ai_generation" not in job.payload and len(calls) == 1
    monkeypatch.setattr(configured, "gemini_default_paid_call_budget", 2)
    assert client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 202
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "succeeded" and len(calls) == 2
    assert session.get(GeminiPaidCallBudget, "version").embedding == 2


def test_postgres_two_workers_compete_for_last_default_call(monkeypatch):
    from threading import Barrier
    from sqlalchemy.engine import make_url
    from lerny.models import GeminiPaidCallBudget

    url = os.environ.get("LERNY_INGESTION_TEST_URL")
    if not url:
        pytest.skip("Requires disposable loopback PostgreSQL")
    assert make_url(url).host == "127.0.0.1" and make_url(url).database.startswith("lerny_ingestion_test_")
    db = create_engine(url)
    tables = [GeminiQuota.__table__, GeminiPaidCallBudget.__table__]
    for table in tables:
        table.create(db)
    config = Settings()
    monkeypatch.setattr(quota, "engine", lambda: db)
    monkeypatch.setattr(quota, "settings", lambda: config)
    monkeypatch.setattr(quota, "request_purpose", lambda path, _: "review" if path == PATH else "embedding")
    barrier = Barrier(2)

    def send(role, path):
        with job_context(SimpleNamespace(id=role, payload={"version_id": "shared"})):
            barrier.wait(timeout=10)
            return quota.reserve_slot(path, BODY)

    try:
        with Session(db) as session:
            session.add(GeminiPaidCallBudget(version_id="shared", review=1400, embedding=99))
            session.commit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, "material", PATH), pool.submit(send, "embedding", "models/test:embedContent")]
        assert sum(f.exception() is None for f in futures) == 1
        assert [str(f.exception()) for f in futures if f.exception()] == ["GEMINI_PAID_CALL_BUDGET_EXCEEDED"]
        with Session(db) as session:
            row = session.get(GeminiPaidCallBudget, "shared")
            assert (row.review, row.embedding) in {(1401, 99), (1400, 100)}
    finally:
        for table in reversed(tables):
            table.drop(db)
        db.dispose()


def test_unexpired_legacy_lease_counts_towards_new_limit(paced, monkeypatch):
    config, clock, db = paced
    config.gemini_review_concurrency = 2
    config.gemini_review_quota_project = "paid"
    config.gemini_review_requests_per_minute = 60
    monkeypatch.setattr(quota, "request_purpose", lambda *_: "review")
    key = quota.scope(PATH, BODY)
    with Session(db) as session:
        session.add(GeminiQuota(key=key, active_token="old", active_until=clock[0]+100))
        session.commit()
    second = quota.reserve_slot(PATH,BODY)
    clock[0] += 2
    pending("GEMINI_PACING_WAIT",lambda: quota.reserve_slot(PATH,BODY))
    quota.release_slot((key, "old"))
    quota.reserve_slot(PATH,BODY)
    with Session(db) as session:
        assert second[1] in session.get(GeminiQuota,key).active_leases

def test_page_link_stages_match_one_gateway_submission(paced, tmp_path, monkeypatch):
    from contextvars import ContextVar
    from PIL import Image
    from lerny.media_materials import service_transport
    from video_extraction.pipeline import document_links
    from video_extraction.shared.gemini import Gemini

    config, _, _ = paced
    config.gemini_review_quota_project = "paid"
    config.gemini_embedding_api_key = SecretStr("synthetic")
    monkeypatch.setenv("LERNY_GEMINI_API_KEY", "synthetic")
    monkeypatch.setattr(quota, "_paid_job", ContextVar("paid", default=True))
    rows = []
    for i in (1,2):
        image = tmp_path/f"page-{i}.png"
        Image.new("RGB", (32,32), (i,0,0)).save(image)
        rows.append({"id": str(i), "source_id":"source", "source_kind":"ppt", "modality":"visual",
                     "image":str(image),"location":{"page":i}})
    model = config.gemini_answer_model
    calls = fake_http(monkeypatch, httpx.Response(200,json={
        "status":"completed","output_text":json.dumps({"links":[],"checks":[]})}))
    transport = lambda req,timeout: service_transport(req,timeout,expected_model=model)
    client = Gemini(tmp_path/"cache",model,None,delay=0,transport=transport)
    task, = document_links.tasks(rows)
    with job_context(SimpleNamespace(id="link",payload={})), quota.verification():
        document_links.run(task,{p["id"]:{"records":[]} for p in rows},tmp_path,client)
    assert (tmp_path/"read.json").is_file() and (tmp_path/"verify.json").is_file()
    assert client.stats["requests"] == 2 and len(calls) == 1
    root = config.runtime_root/"gemini-calls"
    event, = root.glob("*/attempts/*.json")
    assert json.loads(event.read_text())["credential_role"] == "review"

def test_new_worker_rechecks_receipt_published_under_legacy_job_lock(paced, monkeypatch):
    from contextlib import contextmanager
    from threading import Event

    config, _, _ = paced
    job = SimpleNamespace(id="shared-job", payload={})
    root = config.runtime_root/"gemini-calls"/provider.fingerprint((job.id,0))
    cache = root/(provider.fingerprint({"path":PATH,"payload":BODY})+".json")
    entered = Event()
    original = provider.receipt_lock
    @contextmanager
    def observed(path):
        if path == root/"job.lock":
            entered.set()
        with original(path):
            yield
    monkeypatch.setattr(provider,"receipt_lock",observed)
    calls = fake_http(monkeypatch, httpx.Response(200,json={"duplicate":True}))
    def send():
        with job_context(job):
            return provider.request(PATH,BODY,dict)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with original(root/"job.lock"):
            future = pool.submit(send)
            assert entered.wait(5)
            provider.save_json(cache, {"status":"completed","response":{"saved":True}})
        assert future.result() == {"saved":True}
    assert not calls and not (root/"attempts").exists()
