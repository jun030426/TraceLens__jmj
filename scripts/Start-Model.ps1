$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Dev.ps1')
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
& (Join-Path $env:LERNY_RUNTIME_ROOT 'tools\ollama-0.40.2\ollama.exe') serve
