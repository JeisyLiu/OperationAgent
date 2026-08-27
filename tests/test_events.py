import asyncio
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.db.models import Base
from app.db.session import engine
from app.main import app
from app.services.event_bus import event_bus, publish_sync


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_event_bus_publish_subscribe():
    async def run():
        queue = await event_bus.subscribe()
        await event_bus.publish("job.updated", {"job_id": 1, "status": "PENDING"})
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["type"] == "job.updated"
        assert event["payload"]["job_id"] == 1
        await event_bus.unsubscribe(queue)

    asyncio.run(run())


def test_events_sse_endpoint_registered(client: TestClient):
    spec = client.get("/openapi.json").json()
    assert "/api/events" in spec["paths"]


def test_publish_sync_is_safe_to_call():
    publish_sync("readiness.changed", {})
