import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.constants import JobStatus
from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service
from app.services.llm_model_service import llm_model_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_job(db, *, status: str = JobStatus.PENDING.value):
    account = account_service.create(db, platform="tiktok", account_name="republish-user")
    account_service.mark_active(db, account)
    asset = content_service.create_asset(db, title="v", base_caption="base caption", media_type="video")
    content_service.save_upload(db, asset, "demo.mp4", b"data")
    variant = content_service.create_variant(
        db,
        asset_id=asset.id,
        platform="tiktok",
        title="original title",
        caption="original caption",
        status="READY",
    )
    job = job_service.create(
        db,
        content_variant_id=variant.id,
        account_id=account.id,
        scheduled_at=datetime.utcnow(),
    )
    job.status = status
    if status in {JobStatus.SUCCESS.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
        job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return account, asset, variant, job


def _seed_llm(db):
    llm_model_service.create(
        db,
        alias="Primary",
        provider="openai",
        model="gpt-test",
        api_key="sk-test",
        enabled=True,
        priority=0,
    )


def test_retry_rejects_success(client: TestClient):
    db = SessionLocal()
    try:
        _, _, _, job = _seed_job(db, status=JobStatus.SUCCESS.value)
        job_id = job.id
    finally:
        db.close()

    resp = client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 400
    assert "cannot be retried" in resp.json()["detail"].lower()


def test_retry_allows_failed_and_writes_log(client: TestClient):
    db = SessionLocal()
    try:
        _, _, _, job = _seed_job(db, status=JobStatus.FAILED.value)
        job_id = job.id
    finally:
        db.close()

    resp = client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.PENDING.value
    assert resp.json()["retry_count"] == 0

    logs = client.get(f"/api/jobs/{job_id}/logs")
    assert any(log["step"] == "retry" for log in logs.json())


def test_republish_without_rewrite_creates_new_job_same_variant(client: TestClient):
    db = SessionLocal()
    try:
        _, _, variant, job = _seed_job(db, status=JobStatus.SUCCESS.value)
        job_id = job.id
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post(f"/api/jobs/{job_id}/republish", json={"rewrite": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rewritten"] is False
    assert body["variant_id"] == variant_id
    assert body["new_job"]["id"] != job_id
    assert body["new_job"]["content_variant_id"] == variant_id
    assert body["new_job"]["status"] == JobStatus.PENDING.value


def test_republish_preview_rewrite_flags(client: TestClient):
    db = SessionLocal()
    try:
        _seed_llm(db)
        _, _, _, job = _seed_job(db, status=JobStatus.SUCCESS.value)
        job_id = job.id
    finally:
        db.close()

    preview = client.post(f"/api/jobs/{job_id}/republish/preview", json={"rewrite": True})
    assert preview.status_code == 200
    body = preview.json()
    assert body["will_call_content_llm"] is True
    assert body["will_call_execution_llm"] is False
    assert body["variant_mode"] == "clone_variant"
    assert body["warnings"]


def test_republish_rewrite_creates_new_variant(client: TestClient):
    db = SessionLocal()
    try:
        _seed_llm(db)
        _, asset, variant, job = _seed_job(db, status=JobStatus.FAILED.value)
        job_id = job.id
        source_variant_id = variant.id
        new_variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="rewritten title",
            caption="rewritten caption",
            status="DRAFT",
        )
        new_variant_id = new_variant.id
    finally:
        db.close()

    with patch(
        "app.services.content_generate_service.content_generate_service.generate_for_accounts"
    ) as mock_generate:
        mock_generate.return_value = type(
            "R",
            (),
            {"variants": [type("V", (), {"id": new_variant_id})()], "errors": []},
        )()
        resp = client.post(f"/api/jobs/{job_id}/republish", json={"rewrite": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["rewritten"] is True
    assert body["variant_id"] == new_variant_id
    assert body["new_job"]["content_variant_id"] == new_variant_id
    assert body["variant_id"] != source_variant_id


def test_republish_rejects_executing(client: TestClient):
    db = SessionLocal()
    try:
        _, _, _, job = _seed_job(db, status=JobStatus.EXECUTING.value)
        job_id = job.id
    finally:
        db.close()

    resp = client.post(f"/api/jobs/{job_id}/republish", json={"rewrite": False})
    assert resp.status_code == 400


def test_waiting_human_can_republish(client: TestClient):
    db = SessionLocal()
    try:
        _, _, _, job = _seed_job(db, status=JobStatus.WAITING_HUMAN.value)
        job_id = job.id
    finally:
        db.close()

    resp = client.post(f"/api/jobs/{job_id}/republish", json={"rewrite": False})
    assert resp.status_code == 200
    assert resp.json()["new_job"]["status"] == JobStatus.PENDING.value
