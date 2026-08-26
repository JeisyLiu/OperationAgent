import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.base import AgentStatus, AgentTask
from app.agent.openclaw_adapter import OpenClawAdapter
from app.config import settings


def test_openclaw_adapter_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_cmd", None)
    monkeypatch.setattr(settings, "openclaw_base_url", None)
    adapter = OpenClawAdapter()
    result = asyncio.run(
        adapter.execute(
            AgentTask(
                job_id=1,
                platform="bilibili",
                profile_path="profiles/test",
                prompt="test",
            )
        )
    )
    assert result.status == AgentStatus.FAILED
    assert "not configured" in result.message.lower()


def test_openclaw_adapter_cmd_success(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "openclaw_cmd", "fake-openclaw")
    monkeypatch.setattr(settings, "openclaw_base_url", None)
    monkeypatch.setattr(settings, "openclaw_timeout_sec", 30)

    fake_script = tmp_path / "fake-openclaw.cmd"
    fake_script.write_text(
        '@echo off\necho {"status":"SUCCESS","message":"published ok"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda name: str(fake_script) if name == "fake-openclaw" else None)

    async def fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(
            return_value=(b'{"status":"SUCCESS","message":"published ok"}', b"")
        )
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        adapter = OpenClawAdapter()
        result = asyncio.run(
            adapter.execute(
                AgentTask(
                    job_id=1,
                    platform="bilibili",
                    profile_path="profiles/test",
                    prompt="test",
                    execution_dir=str(tmp_path / "exec"),
                )
            )
        )

    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("status") == "SUCCESS"


def test_openclaw_adapter_http_success(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "openclaw_base_url", "http://127.0.0.1:9999")
    monkeypatch.setattr(settings, "openclaw_timeout_sec", 30)

    class FakeResponse:
        def read(self):
            return json.dumps({"status": "SUCCESS", "message": "ok"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        adapter = OpenClawAdapter()
        result = asyncio.run(
            adapter.execute(
                AgentTask(
                    job_id=2,
                    platform="rednote",
                    profile_path="profiles/test",
                    prompt="test",
                    execution_dir=str(tmp_path / "exec2"),
                )
            )
        )

    assert result.status == AgentStatus.SUCCESS
