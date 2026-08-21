import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_job_create_requires_active_account(client: TestClient):
    db = SessionLocal()
    try:
        account = account_service.create(db, platform="tiktok", account_name="a1")
        asset = content_service.create_asset(db, title="v", media_type="video")
        content_service.save_upload(db, asset, "demo.mp4", b"data")
        variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="t",
            caption="c",
        )
        pending_resp = client.post(
            "/api/jobs",
            json={
                "content_variant_id": variant.id,
                "account_id": account.id,
                "scheduled_at": datetime.utcnow().isoformat(),
            },
        )
        assert pending_resp.status_code == 400

        account_service.mark_active(db, account)
        resp = client.post(
            "/api/jobs",
            json={
                "content_variant_id": variant.id,
                "account_id": account.id,
                "scheduled_at": datetime.utcnow().isoformat(),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"
    finally:
        db.close()
