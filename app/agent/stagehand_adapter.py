import logging
from pathlib import Path

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask
from app.agent.tool_loop import run_tool_loop
from app.constants import classify_failure
from app.platforms import require_platform
from app.runtime.playwright_runtime import PlaywrightRuntime
from app.services.content_service import content_service

logger = logging.getLogger(__name__)


class StagehandAdapter(AgentAdapter):
    """Stagehand-style observe-act-verify loop via Playwright + LLM tool actions."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._runtime = PlaywrightRuntime()

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)

        try:
            url = self._resolve_url(task)
            profile_path = Path(task.profile_path)
            if not profile_path.is_absolute():
                profile_path = Path("data") / profile_path

            await self._runtime.open_profile(profile_path, url=url)
            if self._stop_requested:
                return AgentResult(status=AgentStatus.STOPPED, message="Stopped before run")

            page = self._runtime.page
            if page is None:
                raise RuntimeError("Browser page not available")

            media_abs = None
            if task.media_path:
                media_abs = str(content_service.resolve_file_path(task.media_path))

            status, message, screenshots, data = await run_tool_loop(
                page,
                task_prompt=task.prompt,
                media_path=media_abs,
                execution_dir=execution_dir,
            )
            self._status = status
            if status != AgentStatus.SUCCESS:
                data.setdefault("error_code", classify_failure(message))
            data["adapter"] = "stagehand"
            return AgentResult(status=status, message=message, screenshot_paths=screenshots, data=data)
        except Exception as exc:
            logger.exception("StagehandAdapter failed for job %s", task.job_id)
            self._status = AgentStatus.FAILED
            message = str(exc)
            return AgentResult(
                status=AgentStatus.FAILED,
                message=message,
                data={"error_code": classify_failure(message), "adapter": "stagehand"},
            )
        finally:
            await self._runtime.close()

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
        await self._runtime.close()

    def get_status(self) -> AgentStatus:
        return self._status
