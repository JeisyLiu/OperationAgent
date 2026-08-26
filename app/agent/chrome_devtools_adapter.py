import logging
from pathlib import Path

from playwright.async_api import async_playwright

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask
from app.agent.errors import format_adapter_error
from app.agent.tool_loop import run_tool_loop
from app.config import settings
from app.constants import classify_failure
from app.platforms import require_platform
from app.services.content_service import content_service

logger = logging.getLogger(__name__)


class ChromeDevToolsAdapter(AgentAdapter):
    """Attach to user Chrome via CDP and run the shared tool loop."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._playwright = None
        self._browser = None
        self._page = None
        self._owns_page = False

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)

        try:
            url = self._resolve_url(task)
            await self._connect(url)
            if self._stop_requested:
                return AgentResult(status=AgentStatus.STOPPED, message="Stopped before run")

            page = self._page
            if page is None:
                raise RuntimeError("CDP page not available")

            media_abs = None
            if task.media_path:
                media_abs = str(content_service.resolve_file_path(task.media_path))

            status, message, screenshots, data = await run_tool_loop(
                page,
                task_prompt=task.prompt,
                media_path=media_abs,
                execution_dir=execution_dir,
                on_step=task.on_step,
            )
            self._status = status
            if status != AgentStatus.SUCCESS:
                data.setdefault("error_code", classify_failure(message))
            data["adapter"] = "chrome_devtools"
            return AgentResult(status=status, message=message, screenshot_paths=screenshots, data=data)
        except Exception as exc:
            logger.exception("ChromeDevToolsAdapter failed for job %s", task.job_id)
            self._status = AgentStatus.FAILED
            message = format_adapter_error("chrome_devtools", exc)
            return AgentResult(
                status=AgentStatus.FAILED,
                message=message,
                data={"error_code": classify_failure(message), "adapter": "chrome_devtools"},
            )
        finally:
            await self._disconnect()

    async def _connect(self, url: str) -> None:
        cdp_url = settings.chrome_devtools_url
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to Chrome DevTools at {cdp_url}: {exc}"
            ) from exc

        context = self._browser.contexts[0] if self._browser.contexts else None
        if context is None:
            context = await self._browser.new_context()
        self._page = await context.new_page()
        self._owns_page = True
        await self._page.goto(url, wait_until="domcontentloaded")

    async def _disconnect(self) -> None:
        if self._owns_page and self._page is not None:
            try:
                await self._page.close()
            except Exception:
                logger.warning("Failed to close CDP page")
        self._page = None
        self._owns_page = False
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _resolve_url(self, task: AgentTask) -> str:
        try:
            platform = require_platform(task.platform)
            return (
                task.metadata.get("upload_url")
                or task.metadata.get("home_url")
                or platform.upload_url
                or platform.open_url
            )
        except Exception:
            return task.metadata.get("upload_url") or task.metadata.get("home_url") or "https://www.google.com"

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def stop(self) -> None:
        self._stop_requested = True
        self._status = AgentStatus.STOPPED
        await self._disconnect()

    def get_status(self) -> AgentStatus:
        return self._status
