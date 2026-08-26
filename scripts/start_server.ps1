# Start OperationAgent API (no --reload; required on Windows for Playwright).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "Create venv first: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

. .\.venv\Scripts\Activate.ps1
Write-Host "Starting OperationAgent on http://127.0.0.1:8000 (no reload)..." -ForegroundColor Cyan
uvicorn app.main:app --host 127.0.0.1 --port 8000
