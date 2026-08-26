import asyncio
from pathlib import Path

from app.agent.mock_adapter import MockAgentAdapter
from app.channels.base import PublishContext
from app.channels.generic import GenericAgentChannel
from app.channels.registry import get_channel
from app.channels.tiktok import TikTokChannel
from app.constants import FailureCode
from app.db.models import Account, ContentVariant, PublishJob


def test_tiktok_channel_success_with_mock_adapter(tmp_path: Path):
    channel = TikTokChannel()
    adapter = MockAgentAdapter()
    ctx = PublishContext(
        db=None,
        job=PublishJob(id=1, platform="tiktok", browser_profile="profiles/test"),
        account=Account(id=1, status="ACTIVE", platform="tiktok", account_name="a"),
        variant=ContentVariant(id=1, media_path=None, platform="tiktok"),
        adapter=adapter,
        execution_dir=tmp_path,
        prompt="publish",
    )
    result = asyncio.run(channel.publish(ctx))
    assert result.success is True


def test_tiktok_channel_rejects_inactive_account(tmp_path: Path):
    channel = TikTokChannel()
    ctx = PublishContext(
        db=None,
        job=PublishJob(id=1, platform="tiktok"),
        account=Account(id=1, status="PENDING_LOGIN"),
        variant=ContentVariant(id=1, media_path=None),
        adapter=MockAgentAdapter(),
        execution_dir=tmp_path,
        prompt="publish",
    )
    result = asyncio.run(channel.publish(ctx))
    assert result.success is False
    assert result.error_code == FailureCode.LOGIN_REQUIRED.value


def test_registry_returns_tiktok_channel():
    assert isinstance(get_channel("tiktok"), TikTokChannel)


def test_registry_falls_back_to_generic_channel():
    assert isinstance(get_channel("bilibili"), GenericAgentChannel)
