$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    uv run --locked uvicorn lerny.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload --reload-dir apps/api
    if ($LASTEXITCODE -ne 0) { throw 'API process failed.' }
} finally { Pop-Location }
