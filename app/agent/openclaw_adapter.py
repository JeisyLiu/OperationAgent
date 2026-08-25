from app.agent.base import AgentAdapter, AgentResult, AgentStatus, AgentTask


class OpenClawAdapter(AgentAdapter):
    """Reserved adapter slot for OpenClaw. Not wired in MVP."""

    def __init__(self) -> None:
        self._status = AgentStatus.IDLE

    async def execute(self, task: AgentTask) -> AgentResult:
        self._status = AgentStatus.FAILED
        return AgentResult(
            status=AgentStatus.FAILED,
            message="OpenClaw adapter is not wired yet. Use AGENT_ADAPTER=browser_use.",
            data={"error_code": "UNKNOWN"},
        )

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def stop(self) -> None:
        self._status = AgentStatus.STOPPED

    def get_status(self) -> AgentStatus:
        return self._status
