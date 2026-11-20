param(
    [ValidateSet('check','api','web','worker','ingestion')][string]$Component = 'check',
    [string]$RuntimeRoot = $(if ($env:LERNY_RUNTIME_ROOT) { $env:LERNY_RUNTIME_ROOT } elseif (Test-Path (Join-Path $env:USERPROFILE 'LernyPrivateData\secrets\app.json')) { Join-Path $env:USERPROFILE 'LernyPrivateData' } else { Join-Path $env:USERPROFILE 'LernyData' }),
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [switch]$EnableApiCalls
)
$ErrorActionPreference = 'Stop'
if ($env:VERCEL -eq '1' -or $env:LERNY_DEPLOYMENT -eq 'cloud') { throw 'Start-Team is a local-only launcher.' }
$repo = Split-Path $PSScriptRoot -Parent
$toolsRoot = Join-Path $env:USERPROFILE 'LernyData'
$python = Join-Path $toolsRoot 'venvs\team-integration\Scripts\python.exe'
$node = Join-Path $toolsRoot 'tools\node\node.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run uv sync with UV_PROJECT_ENVIRONMENT set to LernyData\venvs\team-integration first. See docs/20_팀원_최신본_통합.md.' }
$env:PYTHONPATH = Join-Path $repo 'apps\api'
$env:PYTHONUTF8 = '1'
$env:LERNY_RUNTIME_ROOT = $RuntimeRoot
$env:LERNY_AI_PROVIDER = 'gemini'
$env:LERNY_GEMINI_CALLS_ENABLED = if ($EnableApiCalls) { 'true' } else { 'false' }
$env:LERNY_API_PROXY_TARGET = "http://127.0.0.1:$ApiPort"
$env:LERNY_ALLOWED_ORIGINS = ConvertTo-Json -Compress -InputObject @("http://127.0.0.1:$WebPort", "http://localhost:$WebPort", "http://127.0.0.1:$ApiPort")
Push-Location $repo
$previousKey = $env:LERNY_GEMINI_API_KEY
try {
    $keyPath = Join-Path $RuntimeRoot 'secrets\gemini-key.dpapi'
    $envPath = if ($env:LERNY_ENV_FILE) { $env:LERNY_ENV_FILE } else { Join-Path $RuntimeRoot 'secrets\team.env' }
    if ($Component -ne 'web' -and -not $previousKey -and -not (Test-Path -LiteralPath $envPath) -and (Test-Path -LiteralPath $keyPath)) {
        $secureKey = ConvertTo-SecureString -String ((Get-Content -LiteralPath $keyPath -Raw).Trim())
        $env:LERNY_GEMINI_API_KEY = [Net.NetworkCredential]::new('', $secureKey).Password.Trim()
        $secureKey.Dispose()
    }
    switch ($Component) {
        'check' { & $python -c 'import json; from lerny.config import settings; from lerny.main import create_app; from lerny.team_engine import ENGINE_VERSION; s=settings(); print(json.dumps(dict(engine=ENGINE_VERSION, database_configured=bool(s.database_url), key_configured=s.gemini_keys_ready(), embedding_key_configured=s.gemini_keys_ready("embedding"), content_key_configured=s.gemini_keys_ready("content"), calls_enabled=s.gemini_calls_enabled, api_routes=len(create_app().openapi()["paths"]))))' }
        'api' { & $python -m uvicorn lerny.main:app --host 127.0.0.1 --port $ApiPort }
        'worker' { & $python -m lerny.worker }
        'ingestion' { & $python -m lerny.ingestion_worker }
        'web' { & $node (Join-Path $repo 'apps\web\node_modules\vite\bin\vite.js') --host 127.0.0.1 --port $WebPort --strictPort --config (Join-Path $repo 'apps\web\vite.config.ts') (Join-Path $repo 'apps\web') }
    }
    if ($LASTEXITCODE -ne 0) { throw "Team $Component exited with code $LASTEXITCODE" }
} finally { $env:LERNY_GEMINI_API_KEY = $previousKey; Pop-Location }
