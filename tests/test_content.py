import io
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


def test_asset_create_requires_base_caption(client: TestClient):
    resp = client.post("/api/content/assets", json={"title": "only title"})
    assert resp.status_code == 422


def test_text_asset_without_media(client: TestClient):
    resp = client.post(
        "/api/content/assets",
        json={"title": "text post", "base_caption": "Body", "tags": ["ai", "tips"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "READY"
    assert data["media_type"] == "text"
    assert data["tags"] == ["ai", "tips"]
    assert data["file_path"] is None

    asset_resp = client.post(
        "/api/content/assets",
        json={"title": "demo video", "base_caption": "Demo description", "media_type": "video"},
    )
    assert asset_resp.status_code == 200
    asset_id = asset_resp.json()["id"]

    upload = client.post(
        f"/api/content/assets/{asset_id}/upload",
        files={"file": ("demo.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert upload.status_code == 200
    assert upload.json()["status"] == "READY"

    variant = client.post(
        "/api/content/variants",
        json={
            "asset_id": asset_id,
            "platform": "tiktok",
            "title": "TikTok title",
            "caption": "caption",
            "hashtags": ["tag1", "tag2"],
        },
    )
    assert variant.status_code == 200
    assert variant.json()["platform"] == "tiktok"
