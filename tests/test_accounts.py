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
