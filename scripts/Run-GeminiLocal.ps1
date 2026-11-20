param(
    [ValidateSet('check', 'api', 'worker')][string]$Mode = 'check',
    [switch]$EnableApiCalls
)
$ErrorActionPreference = 'Stop'
$keyPath = Join-Path $env:USERPROFILE 'LernyPrivateData\secrets\gemini-key.dpapi'
$previousKey = $env:LERNY_GEMINI_API_KEY
try {
    if (-not $env:LERNY_GEMINI_API_KEY -and (Test-Path -LiteralPath $keyPath)) {
        $secureKey = ConvertTo-SecureString -String ((Get-Content -LiteralPath $keyPath -Raw).Trim())
        $env:LERNY_GEMINI_API_KEY = [Net.NetworkCredential]::new('', $secureKey).Password.Trim()
        $secureKey.Dispose()
    }
    $python = Join-Path $env:USERPROFILE 'LernyData\venvs\team-integration\Scripts\python.exe'
    $launcher = Join-Path $PSScriptRoot 'run_gemini_local.py'
    $launchArgs = @($launcher, $Mode)
    if ($EnableApiCalls) { $launchArgs += '--enable-api-calls' }
    & $python @launchArgs
    if ($LASTEXITCODE -ne 0) { throw 'Gemini launcher did not complete successfully.' }
}
finally {
    $env:LERNY_GEMINI_API_KEY = $previousKey
}
