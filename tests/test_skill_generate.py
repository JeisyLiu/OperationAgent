import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.db.models import Base, OperationRun, OperationStep
from tests.conftest import safe_drop_all
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.llm.types import BatchResult
from app.schemas.accounts import AccountSkill


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


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
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="video")
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


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_variants_success(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
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
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="video")
        content_service.save_upload(db, asset, "demo.mp4", b"data")
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=account_id,
            ok=True,
            text='{"title": "T", "caption": "Hello world", "hashtags": ["ai"]}',
        )
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["variants"]) == 1
    assert body["variants"][0]["caption"] == "Hello world"
    assert body["variants"][0]["account_id"] == account_id

    db = SessionLocal()
    try:
        runs = db.query(OperationRun).filter(OperationRun.kind == "generate").all()
        assert len(runs) == 1
        steps = db.query(OperationStep).filter(OperationStep.run_id == runs[0].id).all()
        assert len(steps) >= 1
        assert steps[0].messages_json
        assert steps[0].response_text
    finally:
        db.close()


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_variants_without_media(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="text", tags=["ai"])
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=account_id,
            ok=True,
            text='{"title": "T", "caption": "Text only", "hashtags": [], "section": ""}',
        )
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["variants"][0]["caption"] == "Text only"


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_variants_section_for_bilibili(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="bilibili", account_name="b1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="text")
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=account_id,
            ok=True,
            text='{"title": "B", "caption": "Hello", "hashtags": ["test"], "section": "知识"}',
        )
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    variant = resp.json()["variants"][0]
    assert variant["section"] == "知识"

    patch = client.patch(
        f"/api/content/variants/{variant['id']}",
        json={"section": "生活"},
    )
    assert patch.status_code == 200
    assert patch.json()["section"] == "生活"

    custom = client.patch(
        f"/api/content/variants/{variant['id']}",
        json={"section": "手工"},
    )
    assert custom.status_code == 200
    assert custom.json()["section"] == "手工"


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_variants_keeps_custom_section(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="bilibili", account_name="b2")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="text")
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=account_id,
            ok=True,
            text='{"title": "B", "caption": "Hello", "hashtags": [], "section": "电竞"}',
        )
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["variants"][0]["section"] == "电竞"


def test_build_task_prompt_includes_section():
    from datetime import datetime

    from app.services.job_service import job_service

    db = SessionLocal()
    try:
        account = account_service.create(db, platform="tiktok", account_name="t1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="text")
        variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="t",
            caption="c",
            extra={"section": "Trending"},
        )
        job = job_service.create(
            db,
            content_variant_id=variant.id,
            account_id=account.id,
            scheduled_at=datetime.utcnow(),
        )
        prompt = job_service.build_task_prompt(db, job)
        assert "分区/版块：Trending" in prompt
        assert "发布/上传入口" in prompt
    finally:
        db.close()


def test_generate_prompt_includes_claim_policy(client: TestClient):
    from app.services.content_generate_service import content_generate_service

    template = content_generate_service._load_prompt_template()
    assert "claim_policy" in template
    assert "structure" in template
    assert "Rewrite both title and caption" in template
    assert "do NOT copy verbatim" in template


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_retries_when_copying_source(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="rednote", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(
            db, title="原始标题", base_caption="原始正文内容", media_type="text"
        )
        asset_id = asset.id
        account_id = account.id
    finally:
        db.close()

    mock_chat_batch.side_effect = [
        [
            BatchResult(
                key=account_id,
                ok=True,
                text='{"title": "原始标题", "caption": "原始正文内容", "hashtags": []}',
            )
        ],
        [
            BatchResult(
                key=account_id,
                ok=True,
                text='{"title": "改写后的笔记标题", "caption": "全新改写正文，更适合小红书", "hashtags": ["种草"]}',
            )
        ],
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["variants"]) == 1
    assert body["variants"][0]["title"] == "改写后的笔记标题"
    assert body["variants"][0]["caption"] == "全新改写正文，更适合小红书"
    assert mock_chat_batch.call_count == 2


@patch("app.services.content_generate_service.llm.chat_batch")
def test_rewrite_variant_in_place(mock_chat_batch, client: TestClient):
    db = SessionLocal()
    try:
        from app.services.llm_model_service import llm_model_service

        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(
            db, title="mother title", base_caption="mother caption", media_type="text"
        )
        variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="old title",
            caption="old caption",
            hashtags=["old"],
            extra={
                "account_id": account.id,
                "generated_by": "skill",
                "account_name": account.account_name,
            },
        )
        variant_id = variant.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=1,
            ok=True,
            text='{"title": "fresh title", "caption": "fresh caption body", "hashtags": ["new"]}',
        )
    ]

    resp = client.post(f"/api/content/variants/{variant_id}/rewrite")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == variant_id
    assert body["title"] == "fresh title"
    assert body["caption"] == "fresh caption body"
    assert body["hashtags"] == ["new"]


def test_bulk_jobs_tiktok_and_bilibili(client: TestClient):
    db = SessionLocal()
    try:
        tiktok = account_service.create(db, platform="tiktok", account_name="t1")
        account_service.mark_active(db, tiktok)
        bili = account_service.create(db, platform="bilibili", account_name="b1")
        account_service.mark_active(db, bili)
        asset = content_service.create_asset(db, title="v", base_caption="base", media_type="video")
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
    assert len(body["created"]) == 2
    assert len(body["failed"]) == 0
