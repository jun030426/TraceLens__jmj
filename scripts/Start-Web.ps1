$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'apps\web')
try {
    npm.cmd run dev
    if ($LASTEXITCODE -ne 0) { throw 'Web process failed.' }
} finally { Pop-Location }
