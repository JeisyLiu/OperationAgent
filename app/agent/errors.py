"""Shared agent error formatting and adapter fallback chain helpers."""

from __future__ import annotations

from app.config import settings


def format_adapter_error(
    adapter: str,
    exc: BaseException | None = None,
    *,
    detail: str | None = None,
) -> str:
    """Build a non-empty, actionable failure message for job logs / UI."""
    raw = (detail if detail is not None else (str(exc).strip() if exc else "")).strip()
    exc_name = type(exc).__name__ if exc is not None else None
    lower = raw.lower()

    def with_type(text: str) -> str:
        if exc_name and text and not text.startswith(exc_name):
            return f"{exc_name}: {text}"
        return text or (exc_name or "unknown")

    if exc is not None and isinstance(exc, NotImplementedError):
        return (
            f"[{adapter}] NotImplementedError: Playwright 无法在当前 asyncio 事件循环中拉起浏览器子进程"
            "（Windows 上常见于 uvicorn --reload）。"
            "处理：用 `uvicorn app.main:app --host 127.0.0.1 --port 8000` 无 reload 重启；"
            f"也可走降级链 stagehand → chrome_devtools"
            f"（Chrome --remote-debugging-port=9222，CHROME_DEVTOOLS_URL={settings.chrome_devtools_url}）。"
        )

    if "executable doesn't exist" in lower or "browsertype.launch" in lower:
        return (
            f"[{adapter}] Playwright Chromium 未安装或路径无效：{with_type(raw)}。"
            "处理：在项目 venv 执行 `playwright install chromium`。"
        )

    if (
        adapter == "chrome_devtools"
        or "connection refused" in lower
        or "devtools" in lower
        or "connect_over_cdp" in lower
        or ("connect" in lower and ("9222" in lower or "cdp" in lower))
    ):
        return (
            f"[{adapter}] 无法使用 Chrome DevTools：{with_type(raw)}。"
            f"处理：启动 Chrome `--remote-debugging-port=9222`，并确认 "
            f"CHROME_DEVTOOLS_URL={settings.chrome_devtools_url}；"
            "Windows 上避免 uvicorn --reload。"
        )

    if "langchain" in lower or "no module named" in lower:
        return (
            f"[{adapter}] 依赖缺失：{with_type(raw)}。"
            "处理：安装缺失包，或切换 AGENT_ADAPTER=stagehand / chrome_devtools。"
        )

    if raw:
        return f"[{adapter}] {with_type(raw)}"
    if exc_name:
        return f"[{adapter}] {exc_name}: (无详细信息)"
    return f"[{adapter}] 未知错误（无详细信息）"


def ensure_failure_message(adapter: str | None, message: str | None) -> str:
    text = (message or "").strip()
    if text:
        return text
    name = adapter or "adapter"
    return (
        f"[{name}] 执行失败但未返回错误详情。"
        "常见原因：Playwright 事件循环不支持子进程、Chrome CDP 未启动、或 LLM/依赖未配置。"
        "请查看服务端日志中的完整 traceback。"
    )
