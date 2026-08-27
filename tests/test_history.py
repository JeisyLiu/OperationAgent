import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")

from app.db.models import Base, OperationRun, OperationStep, PublishJob
from tests.conftest import safe_drop_all
from app.db.session import SessionLocal, engine
from app.llm.types import BatchItem, BatchResult, ChatResult, TokenUsage
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service
from app.llm.gateway import LlmGateway


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


@patch("app.llm.gateway.LlmGateway.chat_with_usage")
def test_chat_batch_includes_usage(mock_chat_with_usage):
    mock_chat_with_usage.return_value = ChatResult(
        text="ok",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model_id=1,
        model_alias="Test",
    )
    gateway = LlmGateway()
    results = gateway.chat_batch(
        [BatchItem(key=1, messages=[{"role": "user", "content": "hi"}])],
        max_tokens=16,
    )
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].usage is not None
    assert results[0].usage.total_tokens == 15
    assert results[0].model_alias == "Test"


@patch("app.services.content_generate_service.llm.chat_batch")
def test_generate_creates_operation_audit(mock_chat_batch, client: TestClient):
    from app.services.llm_model_service import llm_model_service

    db = SessionLocal()
    try:
        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="src", base_caption="body", media_type="text")
        account_id = account.id
        asset_id = asset.id
    finally:
        db.close()

    mock_chat_batch.return_value = [
        BatchResult(
            key=account_id,
            ok=True,
            text='{"title": "T", "caption": "Hello world", "hashtags": ["ai"]}',
            usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            model_id=1,
            model_alias="Test",
        )
    ]

    resp = client.post(
        f"/api/content/assets/{asset_id}/generate-variants",
        json={"account_ids": [account_id]},
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        runs = db.query(OperationRun).all()
        assert len(runs) == 1
        assert runs[0].kind == "generate"
        assert runs[0].total_tokens == 30
        steps = db.query(OperationStep).filter(OperationStep.run_id == runs[0].id).all()
        assert len(steps) >= 1
        assert steps[0].messages_json
        assert steps[0].response_text
        assert steps[0].prompt_tokens == 20
    finally:
        db.close()


@patch("app.services.content_generate_service.llm.chat_batch")
def test_rewrite_creates_operation_audit(mock_chat_batch, client: TestClient):
    from app.services.llm_model_service import llm_model_service

    db = SessionLocal()
    try:
        llm_model_service.create(
            db,
            alias="Test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="src", base_caption="body", media_type="text")
        variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="old",
            caption="old cap",
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
            text='{"title": "new", "caption": "new cap", "hashtags": []}',
            usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            model_id=1,
            model_alias="Test",
        )
    ]

    resp = client.post(f"/api/content/variants/{variant_id}/rewrite")
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        runs = db.query(OperationRun).filter(OperationRun.kind == "rewrite").all()
        assert len(runs) == 1
        assert runs[0].status == "success"
        steps = db.query(OperationStep).filter(OperationStep.run_id == runs[0].id).all()
        assert len(steps) >= 1
        assert steps[0].skill_json
    finally:
        db.close()


def test_history_lists_operations_and_jobs(client: TestClient):
    db = SessionLocal()
    try:
        account = account_service.create(db, platform="tiktok", account_name="a1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(db, title="v", base_caption="b", media_type="text")
        variant = content_service.create_variant(
            db, asset_id=asset.id, platform="tiktok", title="t", caption="c"
        )
        job = job_service.create(
            db,
            content_variant_id=variant.id,
            account_id=account.id,
            scheduled_at=__import__("datetime").datetime.utcnow(),
        )
        run = OperationRun(
            kind="generate",
            status="success",
            asset_id=asset.id,
            account_ids_json="[1]",
            variant_ids_json="[1]",
            summary="test generate",
            total_tokens=100,
        )
        db.add(run)
        db.commit()
        job_id = job.id
        run_id = run.id
    finally:
        db.close()

    resp = client.get("/api/history")
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert f"op-{run_id}" in ids
    assert f"job-{job_id}" in ids

    detail = client.get(f"/api/operations/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["kind"] == "generate"
    assert detail.json()["input_snapshot"] is not None
