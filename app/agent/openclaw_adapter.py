import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask
from app.config import settings
from app.constants import classify_failure
from app.platforms import require_platform

logger = logging.getLogger(__name__)


class OpenClawAdapter(AgentAdapter):
    """Execute publish tasks via OpenClaw CLI or HTTP gateway."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._process: subprocess.Popen | None = None

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)

        try:
            if settings.openclaw_base_url:
                return await self._execute_http(task, execution_dir)
            return await self._execute_cmd(task, execution_dir)
        except Exception as exc:
            logger.exception("OpenClawAdapter failed for job %s", task.job_id)
            self._status = AgentStatus.FAILED
            message = str(exc)
            return AgentResult(
                status=AgentStatus.FAILED,
                message=message,
                data={"error_code": classify_failure(message)},
            )

    async def _execute_http(self, task: AgentTask, execution_dir: Path) -> AgentResult:
        base_url = settings.openclaw_base_url.rstrip("/")
        payload = self._build_payload(task, execution_dir)
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            f"{base_url}/v1/tasks",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=settings.openclaw_timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except urlerror.URLError as exc:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message=f"OpenClaw HTTP request failed: {exc}. Check OPENCLAW_BASE_URL.",
                data={"error_code": classify_failure(str(exc))},
            )

        return self._parse_response(raw, execution_dir)

    async def _execute_cmd(self, task: AgentTask, execution_dir: Path) -> AgentResult:
        cmd = settings.openclaw_cmd
        if not cmd:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message=(
                    "OpenClaw is not configured. Set OPENCLAW_CMD (e.g. openclaw) "
                    "or OPENCLAW_BASE_URL in .env, then restart the app."
                ),
                data={"error_code": "UNKNOWN"},
            )

        payload = self._build_payload(task, execution_dir)
        payload_path = execution_dir / "openclaw-task.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        executable = cmd.split()[0]
        if shutil.which(executable) is None:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message=(
                    f"OpenClaw command not found: {executable}. "
                    "Install OpenClaw and set OPENCLAW_CMD, or use OPENCLAW_BASE_URL."
                ),
                data={"error_code": "UNKNOWN"},
            )

        proc = await asyncio.create_subprocess_exec(
            *cmd.split(),
            "--task-file",
            str(payload_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._process = proc
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.openclaw_timeout_sec,
        )
        self._process = None

        if self._stop_requested:
            self._status = AgentStatus.STOPPED
            return AgentResult(status=AgentStatus.STOPPED, message="Stopped by user")

        raw = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message=err or raw or f"OpenClaw exited with code {proc.returncode}",
                data={"error_code": classify_failure(err or raw)},
            )

        return self._parse_response(raw, execution_dir)

    def _build_payload(self, task: AgentTask, execution_dir: Path) -> dict:
        try:
            platform = require_platform(task.platform)
            open_url = platform.upload_url or platform.open_url
        except Exception:
            open_url = task.metadata.get("upload_url") or task.metadata.get("home_url") or ""

        profile_path = Path(task.profile_path)
        if not profile_path.is_absolute():
            profile_path = settings.data_dir / profile_path

        return {
            "job_id": task.job_id,
            "platform": task.platform,
            "prompt": task.prompt,
            "profile_path": str(profile_path),
            "media_path": task.media_path,
            "open_url": open_url,
            "execution_dir": str(execution_dir),
            "metadata": task.metadata,
        }

    def _parse_response(self, raw: str, execution_dir: Path) -> AgentResult:
        data: dict = {}
        message = raw.strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
                message = str(parsed.get("message") or parsed.get("output") or raw).strip()
        except json.JSONDecodeError:
            if "status=SUCCESS" in raw or "status=success" in raw.lower():
                data = {"status": "SUCCESS", "raw": raw[:2000]}
            elif "status=FAILED" in raw or "status=failed" in raw.lower():
                self._status = AgentStatus.FAILED
                return AgentResult(
                    status=AgentStatus.FAILED,
                    message=message or "OpenClaw reported failure",
                    data={"error_code": classify_failure(message)},
                )

        status_text = str(data.get("status", "")).upper()
        if status_text == "SUCCESS" or data.get("success") is True:
            self._status = AgentStatus.SUCCESS
            return AgentResult(
                status=AgentStatus.SUCCESS,
                message=message or "OpenClaw completed",
                data={**data, "status": "SUCCESS", "adapter": "openclaw"},
            )

        self._status = AgentStatus.FAILED
        return AgentResult(
            status=AgentStatus.FAILED,
            message=message or "OpenClaw did not report SUCCESS",
            data={**data, "error_code": classify_failure(message)},
        )

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED
        logger.info("OpenClawAdapter pause requested (no remote pause API)")

    async def stop(self) -> None:
        self._stop_requested = True
        self._status = AgentStatus.STOPPED
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    def get_status(self) -> AgentStatus:
        return self._status
