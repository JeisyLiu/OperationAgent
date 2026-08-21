import asyncio
from pathlib import Path

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask
from app.constants import PLATFORM_URLS
from app.runtime.playwright_runtime import PlaywrightRuntime
from app.services.settings_service import settings_service
from app.db.session import SessionLocal


class BrowserUseAdapter(AgentAdapter):
    """Thin adapter: uses Playwright profile + optional browser-use when available."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._runtime = PlaywrightRuntime()

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)

        url = PLATFORM_URLS.get(task.platform, "https://www.google.com")
        profile_path = Path(task.profile_path)
        if not profile_path.is_absolute():
            profile_path = Path("data") / profile_path

        try:
            await self._runtime.open_profile(profile_path, url=url)
            if self._stop_requested:
                return AgentResult(status=AgentStatus.STOPPED, message="Stopped before run")

            shot_path = execution_dir / "browse.png"
            await self._runtime.screenshot(shot_path)

            # Optional browser-use path for richer tasks when library is installed.
            message = await self._run_browser_use_if_possible(task)
            if message is None:
                message = f"Opened {url} with persistent profile and captured screenshot"

            self._status = AgentStatus.SUCCESS
            return AgentResult(
                status=AgentStatus.SUCCESS,
                message=message,
                screenshot_paths=[str(shot_path)],
            )
        except Exception as exc:
            self._status = AgentStatus.FAILED
            return AgentResult(status=AgentStatus.FAILED, message=str(exc))
        finally:
            await self._runtime.close()

    async def _run_browser_use_if_possible(self, task: AgentTask) -> str | None:
        try:
            from browser_use import Agent as BrowserUseAgent  # type: ignore
            from browser_use import Browser, BrowserConfig  # type: ignore
            from langchain_openai import ChatOpenAI  # type: ignore
        except ImportError:
            return None

        db = SessionLocal()
        try:
            secrets = settings_service.get_secrets(db)
        finally:
            db.close()

        if secrets is None or not secrets.api_key:
            return None

        llm_kwargs = {"api_key": secrets.api_key, "model": secrets.model or "gpt-4o-mini"}
        if secrets.base_url:
            llm_kwargs["base_url"] = secrets.base_url
        llm = ChatOpenAI(**llm_kwargs)

        browser = Browser(config=BrowserConfig(headless=False))
        agent = BrowserUseAgent(task=task.prompt, llm=llm, browser=browser)
        history = await agent.run(max_steps=8)
        return str(history.final_result())[:500] if history else "browser-use completed"

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def stop(self) -> None:
        self._stop_requested = True
        self._status = AgentStatus.STOPPED
        await self._runtime.close()

    def get_status(self) -> AgentStatus:
        return self._status
