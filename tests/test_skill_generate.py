import os
import tempfile
from pathlib import Path
from unittest.mock import patch

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
from app.schemas.accounts import AccountSkill


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_account_skill_roundtrip(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={
            "platform": "tiktok",
            "account_name": "skill-user",
            "persona": "tech reviewer",
            "skill": {
                "tone": "professional",
                "audience": "developers",
                "taboos": ["spam"],
            },
        },
    )
    assert create.status_code == 200
    account_id = create.json()["id"]
    assert create.json()["skill"]["tone"] == "professional"

    patch = client.patch(
        f"/api/accounts/{account_id}",
        json={"skill": {"tone": "casual", "audience": "students", "taboos": []}},
    )
    assert patch.status_code == 200
    assert patch.json()["skill"]["tone"] == "casual"


def test_generate_variants_requires_ai_settings(client: TestClient):
    db = SessionLocal()
    try:
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", media_type="video")
        content_service.save_upload(db, asset, "demo.mp4", b"data")
        account_id = account.id
        asset_id = asset.id
    finally:
        db.close()

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 400


@patch("app.services.content_generate_service.llm_client.chat")
def test_generate_variants_success(mock_chat, client: TestClient):
    mock_chat.return_value = '{"title": "T", "caption": "Hello world", "hashtags": ["ai"]}'
    db = SessionLocal()
    try:
        from app.services.settings_service import settings_service

        settings_service.save(
            db,
            provider="openai",
            base_url=None,
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(
            db,
            platform="tiktok",
            account_name="a1",
            skill=AccountSkill(tone="friendly"),
        )
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", media_type="video", base_caption="base")
        content_service.save_upload(db, asset, "demo.mp4", b"data")
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["variants"]) == 1
    assert body["variants"][0]["caption"] == "Hello world"
    assert body["variants"][0]["account_id"] == account_id


def test_bulk_jobs_tiktok_and_bilibili(client: TestClient):
    db = SessionLocal()
    try:
        tiktok = account_service.create(db, platform="tiktok", account_name="t1")
        account_service.mark_active(db, tiktok)
        bili = account_service.create(db, platform="bilibili", account_name="b1")
        account_service.mark_active(db, bili)
        asset = content_service.create_asset(db, title="v", media_type="video")
        content_service.save_upload(db, asset, "demo.mp4", b"data")
        tiktok_variant = content_service.create_variant(
            db, asset_id=asset.id, platform="tiktok", title="t", caption="c"
        )
        bili_variant = content_service.create_variant(
            db, asset_id=asset.id, platform="bilibili", title="t", caption="c"
        )
        tiktok_id = tiktok.id
        bili_id = bili.id
        tiktok_variant_id = tiktok_variant.id
        bili_variant_id = bili_variant.id
    finally:
        db.close()

    resp = client.post(
        "/api/jobs/bulk",
        json={
            "items": [
                {"content_variant_id": tiktok_variant_id, "account_id": tiktok_id},
                {"content_variant_id": bili_variant_id, "account_id": bili_id},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["created"]) == 1
    assert len(body["failed"]) == 1
    assert "does not support publishing" in body["failed"][0]["detail"]
