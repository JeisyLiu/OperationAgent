"""Ensure Playwright Chromium is installed (auto-heal, no user CLI)."""

from __future__ import annotations

import logging
import subprocess
import sys
from functools import lru_cache

logger = logging.getLogger(__name__)

_MISSING_MARKERS = (
    "executable doesn't exist",
    "playwright install",
    "browsertype.launch",
)


def is_missing_browser_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(m in text for m in _MISSING_MARKERS)


def chromium_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path) and __import__("pathlib").Path(path).exists()
    except Exception:
        return False


def install_chromium() -> tuple[bool, str]:
    """Download Playwright Chromium. Blocks until done."""
    logger.info("Installing Playwright Chromium…")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "安装 Playwright 浏览器超时，请检查网络后点「重试修复」"
    except Exception as exc:
        return False, f"安装 Playwright 浏览器失败：{exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-500:]
        return False, f"安装 Playwright 浏览器失败：{err or f'exit {proc.returncode}'}"

    if not chromium_installed():
        return False, "已执行安装，但仍未找到 Chromium，请点「重试修复」"

    # Bust cache after install
    chromium_ready.cache_clear()
    return True, "已自动安装 Playwright 浏览器"


@lru_cache(maxsize=1)
def chromium_ready() -> bool:
    return chromium_installed()


def ensure_chromium() -> tuple[bool, str]:
    if chromium_ready():
        return True, "Playwright 浏览器已就绪"
    ok, msg = install_chromium()
    if ok:
        chromium_ready.cache_clear()
    return ok, msg
