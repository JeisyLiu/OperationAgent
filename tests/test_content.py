import io
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")

from app.db.models import Base
from tests.conftest import safe_drop_all
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.content_service import content_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_variants():
    db = SessionLocal()
    try:
        asset = content_service.create_asset(db, title="seed asset", base_caption="Body")
        v1 = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="TikTok Alpha",
            caption="caption one",
            status="DRAFT",
            extra={"account_id": 10, "generated_by": "skill", "account_name": "acct-a", "section": "feed"},
        )
        v2 = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="youtube",
            title="YouTube Beta",
            caption="caption two",
            status="READY",
            extra={"account_id": 20, "generated_by": "manual"},
        )
        v3 = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="bilibili",
            title="Bili Gamma",
            caption="search me here",
            status="DRAFT",
            extra={"account_id": 10, "generated_by": "skill"},
        )
        return asset.id, [v1.id, v2.id, v3.id]
    finally:
        db.close()


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


def test_list_variants_paginated_shape(client: TestClient):
    _seed_variants()
    resp = client.get("/api/content/variants")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_list_variants_filter_by_id(client: TestClient):
    _, ids = _seed_variants()
    resp = client.get(f"/api/content/variants?id={ids[1]}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == ids[1]
    assert data["items"][0]["platform"] == "youtube"


def test_list_variants_filter_platform_status(client: TestClient):
    _seed_variants()
    resp = client.get("/api/content/variants?platform=tiktok&status=DRAFT")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["platform"] == "tiktok"
    assert data["items"][0]["status"] == "DRAFT"


def test_list_variants_filter_account_and_generated_by(client: TestClient):
    _seed_variants()
    resp = client.get("/api/content/variants?account_id=10&generated_by=skill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    account_ids = {item["account_id"] for item in data["items"]}
    assert account_ids == {10}
    assert all(item["generated_by"] == "skill" for item in data["items"])


def test_list_variants_keyword_search(client: TestClient):
    _seed_variants()
    resp = client.get("/api/content/variants?q=search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert "search" in (data["items"][0]["caption"] or "")


def test_list_variants_pagination_and_sort(client: TestClient):
    _, ids = _seed_variants()
    resp = client.get("/api/content/variants?page=1&page_size=2&sort=id&order=asc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] < data["items"][1]["id"]

    page2 = client.get("/api/content/variants?page=2&page_size=2&sort=id&order=asc")
    assert page2.status_code == 200
    page2_data = page2.json()
    assert len(page2_data["items"]) == 1
    assert page2_data["items"][0]["id"] == ids[2]


def test_delete_draft_variant(client: TestClient):
    _, ids = _seed_variants()
    draft_id = ids[0]
    ok = client.delete(f"/api/content/variants/{draft_id}")
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    gone = client.get(f"/api/content/variants?id={draft_id}")
    assert gone.json()["total"] == 0


def test_delete_non_draft_variant_rejected(client: TestClient):
    _, ids = _seed_variants()
    ready_id = ids[1]
    resp = client.delete(f"/api/content/variants/{ready_id}")
    assert resp.status_code == 400
