import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")

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


def test_account_create_rejects_unknown_platform(client: TestClient):
    resp = client.post(
        "/api/accounts",
        json={"platform": "invalid-platform", "account_name": "demo"},
    )
    assert resp.status_code == 400


def test_account_delete(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={"platform": "tiktok", "account_name": "demo"},
    )
    account_id = create.json()["id"]
    delete = client.delete(f"/api/accounts/{account_id}")
    assert delete.status_code == 200
    assert client.get("/api/accounts").json() == []


def test_platforms_api(client: TestClient):
    resp = client.get("/api/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["id"] == "tiktok" for p in data)
    tiktok = next(p for p in data if p["id"] == "tiktok")
    assert tiktok["publishable"] is True


def test_account_create_and_list(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={"platform": "tiktok", "account_name": "demo"},
    )
    assert create.status_code == 200
    data = create.json()
    assert data["status"] == "PENDING_LOGIN"
    assert data["browser_profile"].startswith("profiles/")

    listing = client.get("/api/accounts")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
