# One-click start: python -m app.launcher (server + open UI)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Create venv first: python -m venv .venv && .\.venv\Scripts\pip install -e `".[dev]`"" -ForegroundColor Yellow
    exit 1
}

& .\.venv\Scripts\python.exe -m app.launcher
exit $LASTEXITCODE
