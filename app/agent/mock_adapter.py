import asyncio
import random
from pathlib import Path

from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask


class MockAgentAdapter(AgentAdapter):
    def __init__(self, fail_rate: float = 0.0) -> None:
        self._status = AgentStatus.IDLE
        self._stop_requested = False
        self._fail_rate = fail_rate

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        execution_dir = Path(task.execution_dir or f"data/execution/{task.job_id}")
        execution_dir.mkdir(parents=True, exist_ok=True)

        steps = ["claim", "prepare", "execute", "verify"]
        screenshots: list[str] = []

        for step in steps:
            if self._stop_requested:
                self._status = AgentStatus.STOPPED
                return AgentResult(status=AgentStatus.STOPPED, message="Stopped by user")

            await asyncio.sleep(0.05)
            shot = execution_dir / f"{step}.png"
            shot.write_bytes(b"mock-screenshot")
            screenshots.append(str(shot))

        if random.random() < self._fail_rate:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                message="Mock random failure",
                screenshot_paths=screenshots,
            )

        self._status = AgentStatus.SUCCESS
        return AgentResult(
            status=AgentStatus.SUCCESS,
            message="Mock execution completed",
            screenshot_paths=screenshots,
            data={"mock": True},
        )

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def stop(self) -> None:
        self._stop_requested = True
        self._status = AgentStatus.STOPPED

    def get_status(self) -> AgentStatus:
        return self._status
