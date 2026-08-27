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
        return ReadinessCheck("database", CheckStatus.OK, "数据库正常")
    except Exception as exc:
        return ReadinessCheck(
            "database",
            CheckStatus.FAIL,
            f"数据库不可用：{exc}",
            fix="重启应用；若仍失败，删除 data/app.db 后重新启动。",
        )


def _check_worker() -> ReadinessCheck:
    status = worker.get_status()
    if status.get("running") and status.get("lock_held"):
        return ReadinessCheck("worker", CheckStatus.OK, "发布队列已就绪")
    if status.get("running"):
        return ReadinessCheck(
            "worker",
            CheckStatus.WARN,
            "队列在运行，但锁状态异常",
            fix="点「重试修复」，程序会自动整理。",
        )
    return ReadinessCheck(
        "worker",
        CheckStatus.FAIL,
        "发布队列未启动",
        fix="点「重试修复」，程序会自动清理残留锁并拉起队列。",
    )


def _check_llm(db: Session) -> ReadinessCheck:
    enabled = llm_model_service.list_enabled_configs(db)
    if enabled:
        names = ", ".join(c.alias for c in enabled[:3])
        suffix = f" 等 {len(enabled)} 套" if len(enabled) > 1 else ""
        return ReadinessCheck("llm", CheckStatus.OK, f"已配置 LLM：{names}{suffix}")
    return ReadinessCheck(
        "llm",
        CheckStatus.WARN,
        "未配置 LLM（手动上传内容仍可发布）",
        fix="Settings → 添加并启用至少一套模型（用于 AI 生成与重写）。",
    )


def _check_active_accounts(db: Session) -> ReadinessCheck:
    accounts = account_service.list_accounts(db)
    active = [a for a in accounts if a.status == AccountStatus.ACTIVE.value]
    if active:
        return ReadinessCheck(
            "active_accounts",
            CheckStatus.OK,
            f"{len(active)} 个账号已启用，可发布",
        )
    if accounts:
        return ReadinessCheck(
            "active_accounts",
            CheckStatus.WARN,
            f"已有 {len(accounts)} 个账号，但尚未启用",
            fix="Accounts → 点击「登录并启用」，完成平台登录后即可发布。",
        )
    return ReadinessCheck(
        "active_accounts",
        CheckStatus.WARN,
        "还没有账号",
        fix="Accounts → 添加平台账号 →「登录并启用」。",
    )


def _check_adapter() -> ReadinessCheck:
    name = default_adapter_name()
    if name == "mock":
        return ReadinessCheck(
            "adapter",
            CheckStatus.WARN,
            "当前为测试模式，不会真实发布",
            fix="在 .env 中设置 AGENT_ADAPTER=stagehand 后重启。",
        )
    if name == "stagehand":
        return ReadinessCheck("adapter", CheckStatus.OK, "发布将使用已登录的浏览器配置（与登录同一会话）")
    if name == "chrome_devtools":
        return ReadinessCheck("adapter", CheckStatus.OK, "发布将附着到 Chrome 调试端口")
    return ReadinessCheck("adapter", CheckStatus.OK, f"执行方式：{name}")


def _check_windows_event_loop() -> ReadinessCheck | None:
    if sys.platform != "win32":
        return None
    if os.environ.get("UVICORN_RELOAD") == "1" or "--reload" in " ".join(sys.argv):
        return ReadinessCheck(
            "windows_event_loop",
            CheckStatus.FAIL,
            "检测到开发热重载模式，Windows 下可能导致浏览器启动失败",
            fix="请使用一键启动：python -m app.launcher 或 scripts/start.ps1",
        )
    return ReadinessCheck("windows_event_loop", CheckStatus.OK, "Windows 浏览器环境正常")


def _check_chrome_cdp(*, auto_heal: bool = False) -> ReadinessCheck | None:
    if default_adapter_name() != "chrome_devtools":
        return None

    if auto_heal:
        from app.services.chrome_manager import ensure_cdp_ready

        ok, heal_msg = ensure_cdp_ready()
        if not ok:
            return ReadinessCheck(
                "chrome_cdp",
                CheckStatus.FAIL,
                heal_msg,
                fix="请安装 Google Chrome 后点击「重试修复」。",
            )

    url = settings.chrome_devtools_url.rstrip("/")
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{url}/json/version")
            resp.raise_for_status()
            data = resp.json()
            browser = data.get("Browser", "Chrome")
            return ReadinessCheck("chrome_cdp", CheckStatus.OK, f"Chrome 已连接（{browser}）")
    except Exception as exc:
        return ReadinessCheck(
            "chrome_cdp",
            CheckStatus.FAIL,
            f"无法连接 Chrome：{exc}",
            fix="点击「重试修复」，程序会自动启动 Chrome。",
        )


def _first_time_guide(checks: list[ReadinessCheck]) -> list[str]:
    steps = [
        "添加账号 →「登录并启用」完成一次平台登录",
        "上传内容 → 创建变体 → 加入队列",
        "等待发布成功，可在 History 查看步骤与截图",
    ]
    failing = {c.id for c in checks if c.status == CheckStatus.FAIL}
    if "active_accounts" in {c.id for c in checks if c.status == CheckStatus.WARN}:
        steps.insert(0, "先完成账号「登录并启用」")
    if "chrome_cdp" in failing or "worker" in failing:
        steps.insert(0, "点「重试修复」，程序会自动处理")
    return steps


def run_readiness(db: Session, *, auto_heal: bool = False) -> dict:
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
    cdp = _check_chrome_cdp(auto_heal=auto_heal)
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


async def heal_and_readiness(db: Session) -> dict:
    """Auto-fix worker lock / CDP, then return readiness + action log."""
    from app.services.chrome_manager import ensure_cdp_ready

    actions: list[dict] = []

    ok, msg = await worker.ensure_running()
    actions.append({"id": "worker", "ok": ok, "message": msg})

    if default_adapter_name() == "chrome_devtools":
        cdp_ok, cdp_msg = ensure_cdp_ready()
        actions.append({"id": "chrome_cdp", "ok": cdp_ok, "message": cdp_msg})

    report = run_readiness(db, auto_heal=False)
    report["actions"] = actions
    report["healed"] = all(a["ok"] for a in actions) if actions else True
    return report
