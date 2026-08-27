import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.db.models import Base
from tests.conftest import safe_drop_all
from app.db.session import engine
from app.main import app


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_worker_status_endpoint(client: TestClient):
    resp = client.get("/api/worker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body
    assert "adapter_status" in body
    assert "adapter_name" in body


def test_worker_clears_stale_lock_and_starts(tmp_path, monkeypatch):
    import asyncio

    from app.config import settings
    from app.scheduler.worker import SchedulerWorker

    monkeypatch.setattr(settings, "app_data_dir", tmp_path)
    lock = tmp_path / ".worker.lock"
    lock.write_text("99999999", encoding="utf-8")  # almost certainly dead pid

    w = SchedulerWorker()

    async def run():
        ok, msg = await w.ensure_running()
        assert ok is True
        assert w.get_status()["running"] is True
        await w.stop()
        return msg

    msg = asyncio.run(run())
    assert "队列" in msg or "运行" in msg
