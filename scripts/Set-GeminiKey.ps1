$ErrorActionPreference = 'Stop'
$keyPath = Join-Path $env:USERPROFILE 'LernyPrivateData\secrets\gemini-key.dpapi'
$secureKey = Read-Host 'Paste Gemini API key (input is hidden)' -AsSecureString
if ($secureKey.Length -lt 20) { throw 'No key was saved. Enter the complete Gemini API key.' }
New-Item -ItemType Directory -Path (Split-Path -Parent $keyPath) -Force | Out-Null
$secureKey | ConvertFrom-SecureString | Set-Content -LiteralPath $keyPath -Encoding ASCII
$secureKey.Dispose()
Write-Host 'Key saved, encrypted for this Windows user. No API request was made.'
Write-Host $keyPath
