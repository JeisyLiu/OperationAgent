import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.agent.base import AgentStatus, StepEvent
from app.agent.tool_loop import run_tool_loop
from app.constants import FailureCode, JobStatus, StepStatus
from app.db.migrate import run_migrations
from app.db.models import Base, ExecutionLog
from tests.conftest import safe_drop_all
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    run_migrations()
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_publishable_job(db):
    account = account_service.create(db, platform="tiktok", account_name="detail-user")
    account_service.mark_active(db, account)
    asset = content_service.create_asset(db, title="v", base_caption="base", media_type="video")
    content_service.save_upload(db, asset, "demo.mp4", b"data")
    variant = content_service.create_variant(
        db,
        asset_id=asset.id,
        platform="tiktok",
        title="t",
        caption="c",
    )
    job = job_service.create(
        db,
        content_variant_id=variant.id,
        account_id=account.id,
        scheduled_at=datetime.utcnow(),
    )
    return account, variant, job


def test_execution_log_migration_columns_exist():
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("execution_logs")}
    for name in (
        "tool_name",
        "status",
        "duration_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "payload_json",
        "started_at",
    ):
        assert name in columns


def test_job_detail_returns_steps_and_totals(client: TestClient):
    db = SessionLocal()
    try:
        _, _, job = _seed_publishable_job(db)
        job_id = job.id
        account_id = job.account_id
        job_service.add_log(
            db,
            job_id=job.id,
            step="observe-1",
            message="Captured page snapshot",
            tool_name="observe_page",
            status=StepStatus.SUCCESS.value,
            duration_ms=120,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            payload_json=json.dumps({"phase": "observe"}),
        )
        job_service.add_log(
            db,
            job_id=job.id,
            step="llm-1",
            message='{"action":"done"}',
            tool_name="llm_decide",
            status=StepStatus.SUCCESS.value,
            duration_ms=80,
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        )
    finally:
        db.close()

    resp = client.get(f"/api/jobs/{job_id}/detail")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["id"] == job_id
    assert len(body["steps"]) == 2
    assert body["totals"]["duration_ms"] == 200
    assert body["totals"]["prompt_tokens"] == 30
    assert body["totals"]["completion_tokens"] == 15
    assert body["totals"]["total_tokens"] == 45
    assert body["account_id"] == account_id


def test_tool_loop_emits_step_events_with_duration(tmp_path):
    page = MagicMock()
    page.title = AsyncMock(return_value="Creator")
    page.url = "https://example.com/publish"
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock()
    events: list[StepEvent] = []

    def fake_chat(messages):
        if not events:
            return '{"action": "click", "selector": "button.publish"}'
        return '{"action": "done", "message": "status=SUCCESS published ok"}'

    status, message, shots, data = asyncio.run(
        run_tool_loop(
            page,
            task_prompt="publish video",
            media_path=None,
            execution_dir=tmp_path,
            max_steps=3,
            llm_chat=fake_chat,
            on_step=lambda event: events.append(event),
        )
    )
    assert status == AgentStatus.SUCCESS
    assert "SUCCESS" in message
    assert any(e.phase == "observe" and e.duration_ms is not None for e in events)
    assert any(e.phase == "llm" for e in events)
    assert any(e.phase == "done" for e in events)


def test_waiting_human_and_resume(client: TestClient):
    db = SessionLocal()
    try:
        account, _, job = _seed_publishable_job(db)
        job_id = job.id
        job_service.mark_waiting_human(
            db,
            job,
            "Login required",
            error_code=FailureCode.LOGIN_REQUIRED.value,
            action_url=f"/api/accounts/{account.id}/open-profile",
            guidance="请先登录",
        )
        job_service.add_log(
            db,
            job_id=job.id,
            step="waiting_human",
            message="Login required",
            status=StepStatus.WAITING_HUMAN.value,
            payload_json=json.dumps(
                {
                    "error_code": FailureCode.LOGIN_REQUIRED.value,
                    "action_url": f"/api/accounts/{account.id}/open-profile",
                    "guidance": "请先登录",
                }
            ),
        )
    finally:
        db.close()

    detail = client.get(f"/api/jobs/{job_id}/detail")
    assert detail.status_code == 200
    assert detail.json()["job"]["status"] == JobStatus.WAITING_HUMAN.value

    resume = client.post(f"/api/jobs/{job_id}/resume")
    assert resume.status_code == 200
    assert resume.json()["status"] == JobStatus.PENDING.value

    logs = client.get(f"/api/jobs/{job_id}/logs")
    assert any(log["step"] == "resume" for log in logs.json())

    again = client.post(f"/api/jobs/{job_id}/resume")
    assert again.status_code == 400


@patch("app.scheduler.worker.get_channel")
def test_worker_sets_waiting_human_for_login_required(mock_get_channel):
    from app.channels.base import PublishResult
    from app.scheduler.worker import SchedulerWorker

    db = SessionLocal()
    try:
        account, _, job = _seed_publishable_job(db)
        job.status = JobStatus.CLAIMED.value
        db.commit()

        class FakeChannel:
            async def publish(self, ctx):
                return PublishResult(
                    success=False,
                    message="Please sign in to continue",
                    error_code=FailureCode.LOGIN_REQUIRED.value,
                )

        mock_get_channel.return_value = FakeChannel()
        worker = SchedulerWorker()
        asyncio.run(worker._run_job(db, job))

        refreshed = job_service.get(db, job.id)
        assert refreshed.status == JobStatus.WAITING_HUMAN.value
        logs = job_service.get_logs(db, job.id)
        assert any(log.step == "waiting_human" for log in logs)
    finally:
        db.close()
