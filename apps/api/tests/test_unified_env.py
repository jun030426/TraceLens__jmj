"""Credential routing and file isolation; synthetic values, no external calls."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from lerny import gemini_provider
from lerny.config import settings
from lerny.heygen_pilot import load_credentials
from lerny.inference import job_context
from pydantic import SecretStr
from video_extraction.shared.gemini import Blocked, api_key


@pytest.fixture
def unified(tmp_path, monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith(('LERNY_', 'GEMINI_', 'HEYGEN_', 'SUPABASE_', 'VERCEL')) or name in {'DATABASE_URL', 'CRON_SECRET'}:
            monkeypatch.delenv(name)
    monkeypatch.setenv('LERNY_RUNTIME_ROOT', str(tmp_path))
    path = tmp_path / 'secrets/team.env'
    path.parent.mkdir()
    path.write_text('''GEMINI_API_KEY=shared-test
GEMINI_EMBEDDING_API_KEY=embed-test
GEMINI_CONTENT_API_KEY=content-test
GEMINI_CONTENT_MODEL=synthetic-model
HEYGEN_API_KEY="heygen-test-$literal"
HEYGEN_AVATAR_ID=avatar-test
HEYGEN_VOICE_ID=voice-test
DATABASE_URL=postgresql://app:synthetic@localhost:55439/test
SUPABASE_URL=https://synthetic.supabase.co
SUPABASE_SECRET_KEY=sb_secret_synthetic
VERCEL_TOKEN=vercel-test
VERCEL_PROJECT_ID=project-test
LERNY_GEMINI_CALLS_ENABLED=true
''', encoding='utf-8-sig')
    settings.cache_clear()
    yield path
    settings.cache_clear()


def test_one_file_resolves_each_service_without_enabling_calls(unified):
    config = settings()
    assert config.gemini_key('embedding') == 'embed-test'
    assert config.gemini_key('content') == 'content-test'
    assert config.gemini_answer_model == 'synthetic-model'
    assert config.database_url.startswith('postgresql+psycopg://')
    assert config.supabase_service_key.get_secret_value() == 'sb_secret_synthetic'
    assert not config.gemini_calls_enabled
    assert load_credentials() == {'HEYGEN_API_KEY': 'heygen-test-$literal', 'HEYGEN_AVATAR_ID': 'avatar-test', 'HEYGEN_VOICE_ID': 'voice-test'}
    assert api_key(purpose='embedding') == 'embed-test'
    assert api_key(purpose='content') == 'content-test'


def test_transport_uses_role_key_and_never_caches_credentials(unified, monkeypatch):
    config = settings()
    config.gemini_calls_enabled = True
    seen = []
    original_client = httpx.Client
    def receive(request):
        seen.append(request.headers['x-goog-api-key'])
        return httpx.Response(200, json={'value': 'synthetic'})
    monkeypatch.setattr(gemini_provider.httpx, 'Client', lambda **kw: original_client(transport=httpx.MockTransport(receive), **kw))
    with job_context(SimpleNamespace(id='roles', payload={})):
        gemini_provider.request('models/gemini-embedding-2:embedContent', {}, lambda r: r)
        gemini_provider.request('interactions', {}, lambda r: r)
    assert seen == ['embed-test', 'content-test']
    for path in (config.runtime_root/'gemini-calls').rglob('*.json'):
        assert not any(key in path.read_text() for key in seen)


def test_process_overrides_and_common_key_fallback(unified, monkeypatch):
    monkeypatch.setenv('GEMINI_CONTENT_API_KEY', 'process-content')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'process-storage')
    config = settings()
    assert config.gemini_key('content') == 'process-content'
    assert config.supabase_service_key.get_secret_value() == 'process-storage'
    config.gemini_embedding_api_key = SecretStr('')
    assert config.gemini_key('embedding') == 'shared-test'
    config.gemini_api_key = SecretStr('')
    assert config.gemini_keys_ready('content') and not config.gemini_keys_ready('embedding')


def test_vercel_ignores_local_file_and_loads_only_process_settings(unified, monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    for name, value in {'POSTGRES_URL': 'postgres://app:p@cloud.example:6543/postgres',
                        'SUPABASE_URL': 'https://cloud.supabase.co', 'SUPABASE_SECRET_KEY': 'cloud-secret',
                        'VERCEL_PROJECT_PRODUCTION_URL': 'synthetic.vercel.app',
                        'LERNY_AI_WORKER_TOKEN': 'w'*40, 'CRON_SECRET': 'c'*40}.items():
        monkeypatch.setenv(name, value)
    config = settings()
    assert config.gemini_key('embedding') == '' and not config.gemini_calls_enabled
    assert 'cloud.example' in config.database_url
    assert config.supabase_service_key.get_secret_value() == 'cloud-secret'
    with pytest.raises(Blocked, match='missing_api_key'):
        api_key()


def test_vercel_wrapper_passes_only_deployment_values(unified, monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'scripts/run_vercel.py'
    spec = importlib.util.spec_from_file_location('vercel_wrapper', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, 'which', lambda name: 'vercel-test-command')
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', fake_run)
    assert module.main(['--help']) == 0
    assert captured['env']['VERCEL_TOKEN'] == 'vercel-test'
    assert captured['command'] == ['vercel-test-command', '--help']
    assert 'HEYGEN_API_KEY' not in captured['env'] and 'GEMINI_CONTENT_API_KEY' not in captured['env']
