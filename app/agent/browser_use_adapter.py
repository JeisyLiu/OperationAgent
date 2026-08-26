import asyncio
import logging
from pathlib import Path

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask
from app.agent.errors import format_adapter_error
from app.constants import classify_failure
from app.platforms import require_platform
from app.db.session import SessionLocal
from app.runtime.playwright_runtime import PlaywrightRuntime
from app.services.llm_model_service import llm_model_service

logger = logging.getLogger(__name__)


class BrowserUseAdapter(AgentAdapter):
    """Thin adapter: Playwright profile + optional browser-use when available."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._runtime = PlaywrightRuntime()

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)
        screenshots: list[str] = []

        try:
            platform = require_platform(task.platform)
            url = (
                task.metadata.get("upload_url")
                or task.metadata.get("home_url")
                or platform.upload_url
                or platform.open_url
            )
        except Exception:
            url = task.metadata.get("upload_url") or task.metadata.get("home_url") or "https://www.google.com"

        profile_path = Path(task.profile_path)
        if not profile_path.is_absolute():
            profile_path = Path("data") / profile_path

        try:
            await self._runtime.open_profile(profile_path, url=url)
            if self._stop_requested:
                return AgentResult(status=AgentStatus.STOPPED, message="Stopped before run")

            shot_path = execution_dir / "01-open.png"
            await self._runtime.screenshot(shot_path)
            screenshots.append(str(shot_path))

            agent_result = await self._run_browser_use_if_possible(task, execution_dir, screenshots)
            if agent_result is not None:
                return agent_result

            message = f"Opened {url} with persistent profile and captured screenshot"
            self._status = AgentStatus.SUCCESS
            return AgentResult(
                status=AgentStatus.SUCCESS,
                message=message,
                screenshot_paths=screenshots,
                data={"status": "SUCCESS", "mode": "playwright_only"},
            )
        except Exception as exc:
            logger.exception("BrowserUseAdapter failed for job %s", task.job_id)
            self._status = AgentStatus.FAILED
            message = format_adapter_error("browser_use", exc)
            return AgentResult(
                status=AgentStatus.FAILED,
                message=message,
                screenshot_paths=screenshots,
                data={"error_code": classify_failure(message), "adapter": "browser_use"},
            )
        finally:
            await self._runtime.close()

    async def _run_browser_use_if_possible(
        self,
        task: AgentTask,
        execution_dir: Path,
        screenshots: list[str],
    ) -> AgentResult | None:
        try:
            import browser_use  # type: ignore
            from browser_use import Agent as BrowserUseAgent  # type: ignore
            from browser_use import Browser, BrowserConfig  # type: ignore
            from langchain_openai import ChatOpenAI  # type: ignore
        except ImportError:
            return None

        db = SessionLocal()
        try:
            primary = llm_model_service.get_primary_config(db)
        finally:
            db.close()

        if primary is None or not primary.api_key:
            return None
        if primary.provider != "openai":
            logger.warning(
                "Browser agent requires an enabled OpenAI-compatible model; primary is %s",
                primary.provider,
            )
            return None

        llm_kwargs = {"api_key": primary.api_key, "model": primary.model or "gpt-4o-mini"}
        if primary.base_url:
            llm_kwargs["base_url"] = primary.base_url
        llm = ChatOpenAI(**llm_kwargs)

        browser = Browser(config=BrowserConfig(headless=False))
        agent = BrowserUseAgent(task=task.prompt, llm=llm, browser=browser)
        history = await agent.run(max_steps=12)
        final_text = str(history.final_result())[:2000] if history else "browser-use completed"

        shot_path = execution_dir / "02-agent-done.png"
        try:
            await self._runtime.screenshot(shot_path)
            screenshots.append(str(shot_path))
        except Exception:
            logger.warning("Could not capture post-agent screenshot")

        lower = final_text.lower()
        if "status=failed" in lower or "login" in lower or "captcha" in lower:
            error_code = classify_failure(final_text)
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message=final_text,
                screenshot_paths=screenshots,
                data={
                    "error_code": error_code,
                    "browser_use_version": getattr(browser_use, "__version__", "unknown"),
                    "model": llm_kwargs["model"],
                },
            )

        self._status = AgentStatus.SUCCESS
        return AgentResult(
            status=AgentStatus.SUCCESS,
            message=final_text,
            screenshot_paths=screenshots,
            data={
                "status": "SUCCESS",
                "browser_use_version": getattr(browser_use, "__version__", "unknown"),
                "model": llm_kwargs["model"],
            },
        )

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def stop(self) -> None:
        self._stop_requested = True
        self._status = AgentStatus.STOPPED
        await self._runtime.close()

    def get_status(self) -> AgentStatus:
        return self._status
