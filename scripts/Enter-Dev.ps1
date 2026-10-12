# Dot-source this script: . .\scripts\Enter-Dev.ps1
param([string]$RuntimeRoot = $(if ($env:LERNY_RUNTIME_ROOT) { $env:LERNY_RUNTIME_ROOT } else { Join-Path $env:USERPROFILE 'LernyData' }))
$ErrorActionPreference = 'Stop'
$env:LERNY_RUNTIME_ROOT = $RuntimeRoot
$env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $RuntimeRoot 'venvs\api'
$env:PIP_CACHE_DIR = Join-Path $RuntimeRoot 'cache\pip'
$env:npm_config_cache = Join-Path $RuntimeRoot 'cache\npm'
$env:OLLAMA_MODELS = Join-Path $RuntimeRoot 'models\ollama'
$env:OLLAMA_NO_CLOUD = '1'
$env:HF_HOME = Join-Path $RuntimeRoot 'cache\huggingface'
$env:LERNY_DATA_ROOT = Join-Path $RuntimeRoot 'data'
$env:TEMP = Join-Path $RuntimeRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$toolPath = Join-Path $RuntimeRoot 'venvs\bootstrap\Scripts'
if (($env:PATH -split ';') -notcontains $toolPath) {
    $env:PATH = "$toolPath;$env:PATH"
}
$nodePath = Join-Path $RuntimeRoot 'tools\node'
if (Test-Path (Join-Path $nodePath 'node.exe')) {
    $env:PATH = "$nodePath;$env:PATH"
}
Write-Host "Lerny local runtime: $RuntimeRoot"
