import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.agent.base import AgentStatus
from app.agent.tool_loop import run_tool_loop


def test_tool_loop_done_action(tmp_path):
    page = MagicMock()
    page.title = AsyncMock(return_value="Creator")
    page.url = "https://example.com/publish"
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock()

    def fake_chat(messages):
        return '{"action": "done", "message": "status=SUCCESS published ok"}'

    status, message, shots, data = asyncio.run(
        run_tool_loop(
            page,
            task_prompt="publish video",
            media_path=None,
            execution_dir=tmp_path,
            max_steps=3,
            llm_chat=fake_chat,
        )
    )
    assert status == AgentStatus.SUCCESS
    assert "SUCCESS" in message
    assert data.get("status") == "SUCCESS"
