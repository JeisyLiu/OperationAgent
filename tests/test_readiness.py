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


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readiness_endpoint(client: TestClient):
    resp = client.get("/api/health/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body
    assert "checks" in body
    assert "guide" in body
    assert isinstance(body["checks"], list)
    ids = {c["id"] for c in body["checks"]}
    assert "database" in ids
    assert "worker" in ids
    assert "adapter" in ids
