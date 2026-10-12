$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    uv run --locked python scripts/setup_database.py
    if ($LASTEXITCODE -ne 0) { throw 'Database startup failed.' }
    uv run --locked alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    $logRoot = Join-Path $env:LERNY_RUNTIME_ROOT 'logs'
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $shellPath = (Get-Process -Id $PID).Path
    $services = @(
        @{ Name = 'model'; Port = 11434; Script = 'Start-Model.ps1' },
        @{ Name = 'api'; Port = 8000; Script = 'Start-Api.ps1' },
        @{ Name = 'web'; Port = 5173; Script = 'Start-Web.ps1' },
        @{ Name = 'worker'; Port = 0; Script = 'Start-Worker.ps1' }
    )
    foreach ($service in $services) {
        if ($service.Port -gt 0) {
            $listener = Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue
            if ($listener) { Write-Host "$($service.Name): port already in use; existing process left unchanged."; continue }
        } else {
            $worker = Get-CimInstance Win32_Process | Where-Object {
                $_.ExecutablePath -like "$env:LERNY_RUNTIME_ROOT\*python.exe" -and
                $_.CommandLine -match '\-m lerny\.worker(?:\s|$)'
            }
            if ($worker) { Write-Host 'worker: already running.'; continue }
        }
        $scriptPath = Join-Path $PSScriptRoot $service.Script
        $process = Start-Process -FilePath $shellPath -ArgumentList @('-NoProfile', '-File', ('"' + $scriptPath + '"')) -WindowStyle Hidden -PassThru -WorkingDirectory $projectRoot -RedirectStandardOutput (Join-Path $logRoot ($service.Name + '.out.log')) -RedirectStandardError (Join-Path $logRoot ($service.Name + '.err.log'))
        Write-Host "$($service.Name): started process $($process.Id)."
    }
    Write-Host 'Lerny: http://127.0.0.1:5173 (local development only)'
} finally { Pop-Location }
