"""Startup / preflight checks for MVP self-heal UX."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.factory import default_adapter_name
from app.config import settings
from app.constants import AccountStatus
from app.scheduler.worker import worker
from app.services.account_service import account_service
from app.services.llm_model_service import llm_model_service


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class ReadinessCheck:
    id: str
    status: CheckStatus
    message: str
    fix: str | None = None


def _check_database(db: Session) -> ReadinessCheck:
    try:
        db.execute(text("SELECT 1"))
        return ReadinessCheck("database", CheckStatus.OK, "Database reachable")
    except Exception as exc:
        return ReadinessCheck(
            "database",
            CheckStatus.FAIL,
            f"Database error: {exc}",
            fix="Run `python scripts/init_db.py` and restart the server.",
        )


def _check_worker() -> ReadinessCheck:
    status = worker.get_status()
    if status.get("running") and status.get("lock_held"):
        return ReadinessCheck("worker", CheckStatus.OK, "Worker running with exclusive lock")
    if status.get("running"):
        return ReadinessCheck(
            "worker",
            CheckStatus.WARN,
            "Worker running but lock not held — another instance may conflict",
            fix="Stop duplicate uvicorn processes; only one server should run.",
        )
    return ReadinessCheck(
        "worker",
        CheckStatus.FAIL,
        "Worker not running (lock held by another process or failed to start)",
        fix="Stop other OperationAgent instances, delete data/.worker.lock if stale, restart server.",
    )


def _check_llm(db: Session) -> ReadinessCheck:
    enabled = llm_model_service.list_enabled_configs(db)
    if enabled:
        names = ", ".join(c.alias for c in enabled[:3])
        suffix = f" (+{len(enabled) - 3} more)" if len(enabled) > 3 else ""
        return ReadinessCheck("llm", CheckStatus.OK, f"{len(enabled)} LLM config(s) enabled: {names}{suffix}")
    return ReadinessCheck(
        "llm",
        CheckStatus.WARN,
        "No enabled LLM configs — content generation and rewrite-after-republish need Settings",
        fix="Settings → add at least one enabled LLM model with a valid API key.",
    )


def _check_active_accounts(db: Session) -> ReadinessCheck:
    accounts = account_service.list_accounts(db)
    active = [a for a in accounts if a.status == AccountStatus.ACTIVE.value]
    if active:
        return ReadinessCheck(
            "active_accounts",
            CheckStatus.OK,
            f"{len(active)} ACTIVE account(s) ready for publish",
        )
    if accounts:
        return ReadinessCheck(
            "active_accounts",
            CheckStatus.WARN,
            f"{len(accounts)} account(s) exist but none ACTIVE",
            fix="Accounts → Open profile → log in → Mark active.",
        )
    return ReadinessCheck(
        "active_accounts",
        CheckStatus.WARN,
        "No accounts yet",
        fix="Accounts → add a platform account, open profile, log in, mark active.",
    )


def _check_adapter() -> ReadinessCheck:
    name = default_adapter_name()
    if name == "mock":
        return ReadinessCheck(
            "adapter",
            CheckStatus.WARN,
            "AGENT_ADAPTER=mock — jobs will not use a real browser",
            fix="Set AGENT_ADAPTER=chrome_devtools in .env for real publish.",
        )
    return ReadinessCheck("adapter", CheckStatus.OK, f"Default adapter: {name}")


def _check_windows_event_loop() -> ReadinessCheck | None:
    if sys.platform != "win32":
        return None
    policy = os.environ.get("UVICORN_RELOAD", "")
    # Heuristic: reload child processes often lack Proactor policy set in main.py
    if policy == "1" or "--reload" in " ".join(sys.argv):
        return ReadinessCheck(
            "windows_event_loop",
            CheckStatus.FAIL,
            "uvicorn --reload detected on Windows — Playwright subprocess may fail",
            fix="Restart without --reload: uvicorn app.main:app --host 127.0.0.1 --port 8000",
        )
    return ReadinessCheck(
        "windows_event_loop",
        CheckStatus.OK,
        "Windows Proactor event loop policy active (required for Playwright)",
    )


def _check_chrome_cdp() -> ReadinessCheck | None:
    if default_adapter_name() != "chrome_devtools":
        return None
    url = settings.chrome_devtools_url.rstrip("/")
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{url}/json/version")
            resp.raise_for_status()
            data = resp.json()
            browser = data.get("Browser", "Chrome")
            return ReadinessCheck("chrome_cdp", CheckStatus.OK, f"Chrome DevTools reachable ({browser})")
    except Exception as exc:
        return ReadinessCheck(
            "chrome_cdp",
            CheckStatus.FAIL,
            f"Cannot reach Chrome DevTools at {url}: {exc}",
            fix=(
                'Start Chrome with remote debugging, e.g.\n'
                '  scripts/start_chrome_cdp.ps1\n'
                'or: chrome.exe --remote-debugging-port=9222 --user-data-dir="%TEMP%\\oa-chrome"'
            ),
        )


def _first_time_guide(checks: list[ReadinessCheck]) -> list[str]:
    steps = [
        "1. Copy `.env.example` → `.env` (default AGENT_ADAPTER=chrome_devtools).",
        "2. Start server: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (no --reload on Windows).",
        "3. Settings → add enabled LLM config (optional for queue-only tests).",
        "4. Start Chrome CDP: `scripts/start_chrome_cdp.ps1` (or equivalent command).",
        "5. Accounts → Open profile → log in manually → Mark active.",
        "6. Content → upload asset → create variant → Queue → wait for SUCCESS.",
    ]
    failing = {c.id for c in checks if c.status == CheckStatus.FAIL}
    if "chrome_cdp" in failing:
        steps.insert(3, "→ Fix CDP first: Chrome must be running with --remote-debugging-port=9222")
    if "worker" in failing:
        steps.insert(2, "→ Fix worker: stop duplicate servers / remove stale data/.worker.lock")
    return steps


def run_readiness(db: Session) -> dict:
    checks: list[ReadinessCheck] = [
        _check_database(db),
        _check_worker(),
        _check_adapter(),
        _check_llm(db),
        _check_active_accounts(db),
    ]
    win = _check_windows_event_loop()
    if win:
        checks.append(win)
    cdp = _check_chrome_cdp()
    if cdp:
        checks.append(cdp)

    blocking = [c for c in checks if c.status == CheckStatus.FAIL]
    ready = len(blocking) == 0

    return {
        "ready": ready,
        "adapter": default_adapter_name(),
        "chrome_devtools_url": settings.chrome_devtools_url,
        "checks": [
            {
                "id": c.id,
                "status": c.status.value,
                "message": c.message,
                "fix": c.fix,
            }
            for c in checks
        ],
        "guide": _first_time_guide(checks),
    }
