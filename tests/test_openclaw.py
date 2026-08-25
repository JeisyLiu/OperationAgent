import asyncio

from app.agent.openclaw_adapter import OpenClawAdapter
from app.agent.base import AgentStatus, AgentTask


def test_openclaw_adapter_not_wired():
    adapter = OpenClawAdapter()
    result = asyncio.run(
        adapter.execute(
            AgentTask(
                job_id=1,
                platform="tiktok",
                profile_path="profiles/test",
                prompt="test",
            )
        )
    )
    assert result.status == AgentStatus.FAILED
    assert "not wired" in result.message.lower()
