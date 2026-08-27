# One-click start for Windows: create venv, install deps, launch UI.
# Prerequisite: Python 3.11+ on PATH (py -3.11 or python).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Find-Python {
    $candidates = @("py", "python", "python3")
    foreach ($cmd in $candidates) {
        try {
            $ver = & $cmd --version 2>&1 | Out-String
            if ($ver -match "Python 3\.(1[1-9]|[2-9]\d)") {
                return $cmd
            }
        } catch { }
    }
    # py launcher with -3.11
    try {
        $ver = & py -3.11 --version 2>&1 | Out-String
        if ($ver -match "Python") { return "py -3.11" }
    } catch { }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "需要已安装 Python 3.11+，并加入 PATH。安装后重新运行本脚本。" -ForegroundColor Red
    Write-Host "下载：https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

$venvPy = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment (.venv)…" -ForegroundColor Cyan
    if ($py -eq "py -3.11") {
        & py -3.11 -m venv .venv
    } else {
        & $py -m venv .venv
    }
    if (-not (Test-Path $venvPy)) {
        Write-Host "创建 .venv 失败" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Ensuring package install…" -ForegroundColor Cyan
& $venvPy -m pip install -U pip setuptools wheel | Out-Null
& $venvPy -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install 失败，请检查网络后重试" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Launching OperationAgent…" -ForegroundColor Cyan
& $venvPy -m app.launcher
exit $LASTEXITCODE
