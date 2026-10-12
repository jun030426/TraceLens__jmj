$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'apps\api')
try { uv run --project ..\.. --locked python -m lerny.worker }
finally { Pop-Location }
