# Launch Chrome with remote debugging for chrome_devtools adapter.
$ErrorActionPreference = "Stop"

$port = if ($env:CHROME_DEBUG_PORT) { $env:CHROME_DEBUG_PORT } else { "9222" }
$userData = if ($env:CHROME_USER_DATA) { $env:CHROME_USER_DATA } else { Join-Path $env:TEMP "oa-chrome" }

$chromePaths = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "${env:LOCALAPPDATA}\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Host "Chrome not found. Install Google Chrome or set path manually." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $userData | Out-Null
Write-Host "Chrome CDP: port=$port user-data-dir=$userData" -ForegroundColor Cyan
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$userData",
    "about:blank"
)
