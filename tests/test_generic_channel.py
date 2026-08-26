import asyncio
from datetime import datetime

import pytest

from app.agent.mock_adapter import MockAgentAdapter
from app.channels.generic import GenericAgentChannel
from app.channels.base import PublishContext
from app.constants import AccountStatus
from app.db.models import Account, ContentAsset, ContentVariant, PublishJob
from app.services.content_service import content_service


class _FakeDb:
    pass


@pytest.fixture
def generic_channel():
    return GenericAgentChannel()


@pytest.fixture
def mock_ctx(tmp_path):
    account = Account(
        id=1,
        platform="bilibili",
        account_name="tester",
        browser_profile="profiles/b1",
        status=AccountStatus.ACTIVE.value,
    )
    asset = ContentAsset(id=1, title="t", media_type="text", status="READY")
    variant = ContentVariant(
        id=10,
        asset_id=1,
        platform="bilibili",
        title="title",
        caption="caption",
        status="DRAFT",
        extra_json='{"section": "科技"}',
    )
    job = PublishJob(
        id=100,
        content_variant_id=10,
        account_id=1,
        platform="bilibili",
        browser_profile="profiles/b1",
        scheduled_at=datetime.utcnow(),
        status="EXECUTING",
    )

    return PublishContext(
        db=_FakeDb(),
        job=job,
        account=account,
        variant=variant,
        adapter=MockAgentAdapter(),
        execution_dir=tmp_path / "exec",
        prompt="publish prompt",
    )


def test_generic_channel_success(generic_channel, mock_ctx):
    result = asyncio.run(generic_channel.publish(mock_ctx))
    assert result.success is True
    assert "SUCCESS" in result.message or result.data.get("verify")


def test_generic_channel_requires_active_account(generic_channel, mock_ctx):
    mock_ctx.account.status = AccountStatus.PENDING_LOGIN.value
    result = asyncio.run(generic_channel.publish(mock_ctx))
    assert result.success is False
    assert result.error_code == "LOGIN_REQUIRED"


def test_generic_channel_missing_media(generic_channel, mock_ctx, tmp_path, monkeypatch):
    mock_ctx.variant.media_path = "content/99/missing.mp4"
    monkeypatch.setattr(
        content_service,
        "resolve_file_path",
        lambda rel: tmp_path / "missing.mp4",
    )
    result = asyncio.run(generic_channel.publish(mock_ctx))
    assert result.success is False
    assert "missing" in result.message.lower()
