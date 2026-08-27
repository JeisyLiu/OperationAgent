#!/usr/bin/env bash
# One-click start: create venv, install deps, launch UI.
# Prerequisite: Python 3.11+ on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Need Python 3.11+ on PATH"
  exit 1
fi

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment (.venv)…"
  "$PY" -m venv .venv
fi

echo "Ensuring package install…"
.venv/bin/python -m pip install -U pip setuptools wheel >/dev/null
.venv/bin/python -m pip install -e .

echo "Launching OperationAgent…"
exec .venv/bin/python -m app.launcher
