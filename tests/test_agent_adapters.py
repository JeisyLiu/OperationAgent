import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.base import AgentStatus, AgentTask
from app.agent.factory import (
    adapter_name_for_platform,
    create_agent_adapter,
    default_adapter_name,
    resolve_adapter_for_platform,
)
from app.agent.chrome_devtools_adapter import ChromeDevToolsAdapter
from app.agent.stagehand_adapter import StagehandAdapter


def test_create_stagehand_adapter():
    adapter = create_agent_adapter("stagehand")
    assert isinstance(adapter, StagehandAdapter)


def test_create_chrome_devtools_adapter():
    adapter = create_agent_adapter("chrome_devtools")
    assert isinstance(adapter, ChromeDevToolsAdapter)


def test_default_adapter_is_chrome_devtools(monkeypatch):
    from app.config import settings

    settings.agent_adapter = "chrome_devtools"
    assert default_adapter_name() == "chrome_devtools"
    assert isinstance(create_agent_adapter(), ChromeDevToolsAdapter)


def test_should_fallback_to_chrome_on_empty_or_playwright_error():
    from app.agent.factory import is_infra_failure, next_fallback_adapter, should_fallback_to_chrome

    assert next_fallback_adapter("browser_use") == "stagehand"
    assert next_fallback_adapter("stagehand") == "chrome_devtools"
    assert next_fallback_adapter("chrome_devtools") is None
    assert should_fallback_to_chrome("browser_use", "", "UNKNOWN")
    assert should_fallback_to_chrome("stagehand", "NotImplementedError: spawn", None)
    assert not should_fallback_to_chrome("chrome_devtools", "", None)
    assert not should_fallback_to_chrome("browser_use", "Please sign in to continue", "LOGIN_REQUIRED")
    assert is_infra_failure("", None)
    assert not is_infra_failure("captcha blocked", "CAPTCHA_BLOCKED")


def test_format_adapter_error_is_clear():
    from app.agent.errors import ensure_failure_message, format_adapter_error

    msg = format_adapter_error("browser_use", NotImplementedError())
    assert "browser_use" in msg
    assert "NotImplementedError" in msg
    assert "处理" in msg
    assert ensure_failure_message("stagehand", "") != ""
    assert "stagehand" in ensure_failure_message("stagehand", "")


def test_rednote_prefers_chrome_devtools():
    assert adapter_name_for_platform("rednote") == "chrome_devtools"
    adapter = resolve_adapter_for_platform("rednote")
    assert isinstance(adapter, ChromeDevToolsAdapter)


def test_tiktok_uses_global_adapter(monkeypatch):
    monkeypatch.setenv("AGENT_ADAPTER", "mock")
    from app.config import settings

    settings.agent_adapter = "mock"
    assert adapter_name_for_platform("tiktok") == "mock"


def test_stagehand_adapter_success(monkeypatch):
    mock_page = MagicMock()
    runtime = MagicMock()
    runtime.page = mock_page
    runtime.open_profile = AsyncMock()
    runtime.close = AsyncMock()

    async def fake_loop(*args, **kwargs):
        return AgentStatus.SUCCESS, "status=SUCCESS published", ["/tmp/s.png"], {"status": "SUCCESS"}

    with patch("app.agent.stagehand_adapter.PlaywrightRuntime", return_value=runtime), patch(
        "app.agent.stagehand_adapter.run_tool_loop", side_effect=fake_loop
    ):
        adapter = StagehandAdapter()
        result = asyncio.run(
            adapter.execute(
                AgentTask(
                    job_id=1,
                    platform="bilibili",
                    profile_path="profiles/test",
                    prompt="publish",
                    metadata={"upload_url": "https://example.com/upload"},
                )
            )
        )

    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("adapter") == "stagehand"


def test_chrome_devtools_adapter_cdp_failure():
    adapter = ChromeDevToolsAdapter()
    with patch(
        "app.agent.chrome_devtools_adapter.async_playwright",
        side_effect=RuntimeError("connection refused"),
    ):
        result = asyncio.run(
            adapter.execute(
                AgentTask(
                    job_id=2,
                    platform="rednote",
                    profile_path="profiles/test",
                    prompt="publish",
                )
            )
        )
    assert result.status == AgentStatus.FAILED
    assert "9222" in result.message or "CHROME_DEVTOOLS_URL" in result.message


def test_chrome_devtools_adapter_success(monkeypatch, tmp_path):
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = MagicMock()
    mock_browser.contexts = []
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = MagicMock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_playwright.stop = AsyncMock()

    mock_pw_factory = MagicMock()
    mock_pw_factory.start = AsyncMock(return_value=mock_playwright)

    async def fake_loop(*args, **kwargs):
        return AgentStatus.SUCCESS, "status=SUCCESS", [], {"status": "SUCCESS"}

    with patch("app.agent.chrome_devtools_adapter.async_playwright", return_value=mock_pw_factory), patch(
        "app.agent.chrome_devtools_adapter.run_tool_loop", side_effect=fake_loop
    ):
        adapter = ChromeDevToolsAdapter()
        result = asyncio.run(
            adapter.execute(
                AgentTask(
                    job_id=3,
                    platform="rednote",
                    profile_path="profiles/test",
                    prompt="publish",
                    execution_dir=str(tmp_path),
                )
            )
        )

    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("adapter") == "chrome_devtools"
