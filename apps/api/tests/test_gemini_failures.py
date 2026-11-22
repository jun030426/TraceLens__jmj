"""Real durable cache + synthetic HTTP failures; no provider or production calls."""
import json
from types import SimpleNamespace

import httpx
import pytest
from lerny import gemini_provider as provider, gemini_failures as failures
from lerny.inference import job_context
from lerny.gemini_quota import ProviderDeferred
from test_gemini_quota import paced, PATH, BODY  # noqa: F401


def test_five_service_failures_stop_across_restarts_and_explicit_retry_keeps_successes(paced, monkeypatch):
    config, clock, _ = paced
    calls = []
    recovering = [False]
    def post(_self, url, **kwargs):
        body = kwargs['json']; calls.append(body['input'])
        good = body['input'] == 'completed-step' or recovering[0]
        return httpx.Response(200 if good else 503,
            json={'ok': True} if good else {'error': {'code': 'service_unavailable',
                'message': 'The model is overloaded. Please try again later.'}},
            headers={'x-request-id': 'safe-request-id'}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', post)
    job = SimpleNamespace(id='resume-job', payload={}, error_code=None)
    with job_context(job):
        provider.request(PATH, {**BODY, 'input': 'completed-step'}, lambda raw: raw)
    clock[0] += 6
    for attempt in range(1, 6):
        # A new context represents a new process attempt; only disk/DB retain state.
        with job_context(job), pytest.raises(ValueError) as caught:
            provider.request(PATH, BODY, lambda raw: raw)
        if attempt < 5:
            assert isinstance(caught.value, ProviderDeferred)
            assert caught.value.retry_at >= clock[0] + 30 * 2 ** (attempt - 1)
            clock[0] = caught.value.retry_at + 1
        else:
            assert str(caught.value) == failures.EXHAUSTED
    before = len(calls)
    clock[0] += 1000
    with job_context(job), pytest.raises(ValueError, match=failures.EXHAUSTED):
        provider.request(PATH, BODY, lambda raw: raw)
    assert len(calls) == before == 6
    diagnostic = next(config.runtime_root.rglob('diagnostics/latest.json'))
    assert json.loads(diagnostic.read_text())['service_failures'] == 5
    job.error_code = failures.EXHAUSTED
    failures.prepare_retry(job)
    assert job.payload.get('_ai_generation', 0) == 0
    recovering[0] = True
    with job_context(job):
        assert provider.request(PATH, {**BODY, 'input': 'completed-step'}, lambda raw: raw)['ok']
        assert provider.request(PATH, BODY, lambda raw: raw)['ok']
    assert calls.count('completed-step') == 1 and len(calls) == 7
    attempts = list(config.runtime_root.glob('gemini-calls/*/attempts/*.json'))
    assert len(attempts) == len(calls) and sum(p.name.endswith('.retry.json') for p in attempts) == 5


def test_diagnostics_do_not_log_echoed_secrets_or_source_text():
    secret = 'AIzaSYNTHETIC-DO-NOT-LOG'
    body = {'error': {'code': 'service_unavailable', 'message': f'{secret} PRIVATE SOURCE',
                      'details': [{'request': {'api_key': secret, 'input': 'PRIVATE SOURCE'}}]}}
    response = httpx.Response(503, json=body, headers={'x-request-id': 'invalid secret\tvalue'})
    detail = failures.diagnostic(response, {'model': 'gemini-test', 'input': 'PRIVATE SOURCE'}, 'a'*64, 1, 0, .2)
    assert secret not in json.dumps(detail) and 'PRIVATE SOURCE' not in json.dumps(detail)
    assert detail['message'] is None and detail['message_omitted']
    assert detail['request_id'] is None and detail['provider_code'] == 'service_unavailable'
    assert detail['http_status'] == 503 and detail['elapsed_ms'] == 200


def test_uncertain_failures_still_require_fresh_generation():
    job = SimpleNamespace(payload={'_ai_generation': 3}, error_code='GEMINI_CALL_UNCERTAIN')
    failures.prepare_retry(job)
    assert job.payload['_ai_generation'] == 4
