"""Managed Chrome CDP lifecycle for chrome_devtools adapter."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_started_pid: int | None = None


def is_cdp_reachable(url: str | None = None) -> bool:
    base = (url or settings.chrome_devtools_url).rstrip("/")
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{base}/json/version")
            return resp.status_code == 200
    except Exception:
        return False


def _find_chrome_executable() -> Path | None:
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_cdp_port(url: str) -> int:
    parsed = urlparse(url)
    return parsed.port or 9222


def ensure_cdp_ready() -> tuple[bool, str]:
    """Start Chrome with remote debugging if CDP is not already reachable."""
    global _started_pid

    if is_cdp_reachable():
        return True, "Chrome DevTools already reachable"

    chrome = _find_chrome_executable()
    if chrome is None:
        return False, "Google Chrome not found on this machine"

    port = _parse_cdp_port(settings.chrome_devtools_url)
    user_data = Path(tempfile.gettempdir()) / "oa-chrome"
    user_data.mkdir(parents=True, exist_ok=True)

    args = [
        str(chrome),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "about:blank",
    ]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    _started_pid = proc.pid
    logger.info("Started Chrome for CDP pid=%s port=%s", proc.pid, port)

    for _ in range(30):
        if is_cdp_reachable():
            return True, f"Started Chrome for DevTools (pid={proc.pid})"
        time.sleep(0.5)

    return False, "Chrome started but DevTools endpoint did not become ready"


def shutdown_managed_chrome() -> None:
    global _started_pid
    if _started_pid is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(_started_pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(_started_pid, 15)
    except Exception:
        logger.exception("Failed to stop managed Chrome pid=%s", _started_pid)
    _started_pid = None
