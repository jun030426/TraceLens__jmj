param([string]$Config = (Join-Path $env:USERPROFILE 'LernyData\secrets\ai-runner.json'))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
if (-not (Test-Path -LiteralPath $Config)) { throw 'Create the external ai-runner.json using docs/16 first.' }
& (Join-Path $env:LERNY_RUNTIME_ROOT 'venvs\api\Scripts\python.exe') (Join-Path $PSScriptRoot 'ai_runner.py') --config $Config
