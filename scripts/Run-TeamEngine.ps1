param(
    [ValidateSet('rag','quiz','media')][string]$Engine = 'rag',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$EngineArguments
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$runtime = if ($env:LERNY_RUNTIME_ROOT) { $env:LERNY_RUNTIME_ROOT } elseif (Test-Path (Join-Path $env:USERPROFILE 'LernyPrivateData\secrets\app.json')) { Join-Path $env:USERPROFILE 'LernyPrivateData' } else { Join-Path $env:USERPROFILE 'LernyData' }
$python = Join-Path $env:USERPROFILE 'LernyData\venvs\team-integration\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $repo 'apps\api'
$env:PYTHONUTF8 = '1'
$env:LERNY_RUNTIME_ROOT = $runtime
$env:LERNY_ENGINE_ROOT = Join-Path $runtime 'team-engine'
$module = @{ rag='rag_mvp'; quiz='quiz_mvp'; media='video_extraction.pipeline.connected' }[$Engine]
if (-not $EngineArguments) { $EngineArguments = @('--help') }
Push-Location $repo
try { & $python -m $module @EngineArguments; if ($LASTEXITCODE -ne 0) { throw "Engine exited with code $LASTEXITCODE" } }
finally { Pop-Location }
