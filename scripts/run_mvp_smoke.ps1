# MVP acceptance: 3 consecutive publish smoke runs with report.
param(
    [Parameter(Mandatory = $true)][int]$VariantId,
    [Parameter(Mandatory = $true)][int]$AccountId,
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Runs = 3
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Run from repo root with .venv installed." -ForegroundColor Red
    exit 1
}

$report = Join-Path "data" "smoke_report.json"
Write-Host "MVP smoke: $Runs runs, variant=$VariantId account=$AccountId" -ForegroundColor Cyan
Write-Host "Prerequisites: server running, Chrome CDP (scripts/start_chrome_cdp.ps1), ACTIVE account" -ForegroundColor Yellow

& .\.venv\Scripts\python.exe scripts\smoke_publish.py `
    --base-url $BaseUrl `
    --variant-id $VariantId `
    --account-id $AccountId `
    --runs $Runs `
    --report $report

exit $LASTEXITCODE
