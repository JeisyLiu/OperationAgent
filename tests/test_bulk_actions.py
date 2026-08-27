import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.constants import AccountStatus, JobStatus
from app.db.models import Base
from tests.conftest import safe_drop_all
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
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_account(db, *, name="acct", active=False):
    account = account_service.create(db, platform="tiktok", account_name=name)
    if active:
        account_service.mark_active(db, account)
    return account


def _seed_variant(db, account, *, status="DRAFT"):
    asset = content_service.create_asset(db, title="asset", base_caption="body", media_type="text")
    return content_service.create_variant(
        db,
        asset_id=asset.id,
        platform="tiktok",
        title="title",
        caption="caption",
        status=status,
        extra={"account_id": account.id, "account_name": account.account_name},
    )


def test_accounts_bulk_disable_enable_delete(client: TestClient):
    db = SessionLocal()
    try:
        active = _seed_account(db, name="active", active=True)
        pending = _seed_account(db, name="pending")
        disabled = account_service.create(db, platform="tiktok", account_name="disabled")
        account_service.update(db, disabled, status=AccountStatus.DISABLED.value)
        active_id, pending_id, disabled_id = active.id, pending.id, disabled.id
    finally:
        db.close()

    disable = client.post(
        "/api/accounts/bulk",
        json={"ids": [active_id, pending_id], "action": "disable"},
    )
    assert disable.status_code == 200
    body = disable.json()
    assert body["action"] == "disable"
    assert set(body["succeeded"]) == {active_id, pending_id}
    assert body["failed"] == []
    assert body["ok"] is True

    enable = client.post(
        "/api/accounts/bulk",
        json={"ids": [disabled_id], "action": "enable"},
    )
    assert enable.status_code == 200
    assert enable.json()["succeeded"] == [disabled_id]
    listed = {a["id"]: a["status"] for a in client.get("/api/accounts").json()}
    assert listed[disabled_id] == AccountStatus.PENDING_LOGIN.value

    delete = client.post(
        "/api/accounts/bulk",
        json={"ids": [active_id, 99999], "action": "delete"},
    )
    assert delete.status_code == 200
    result = delete.json()
    assert result["ok"] is False
    assert active_id in result["succeeded"]
    assert result["failed"][0]["id"] == 99999


def test_accounts_bulk_invalid_action(client: TestClient):
    resp = client.post("/api/accounts/bulk", json={"ids": [1], "action": "login"})
    assert resp.status_code == 400


def test_disabled_account_cannot_create_job(client: TestClient):
    db = SessionLocal()
    try:
        account = _seed_account(db, name="to-disable", active=True)
        variant = _seed_variant(db, account, status="READY")
        account_service.update(db, account, status=AccountStatus.DISABLED.value)
        account_id, variant_id = account.id, variant.id
    finally:
        db.close()

    resp = client.post(
        "/api/jobs",
        json={
            "content_variant_id": variant_id,
            "account_id": account_id,
            "scheduled_at": datetime.utcnow().isoformat(),
        },
    )
    assert resp.status_code == 400


def test_variants_bulk_delete_and_enqueue(client: TestClient):
    db = SessionLocal()
    try:
        account = _seed_account(db, name="pub", active=True)
        draft = _seed_variant(db, account, status="DRAFT")
        ready = _seed_variant(db, account, status="READY")
        asset = content_service.get_asset(db, draft.asset_id)
        no_account = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="orphan",
            caption="c",
            status="DRAFT",
        )
        draft_id, ready_id, no_account_id = draft.id, ready.id, no_account.id
    finally:
        db.close()

    delete = client.post(
        "/api/content/variants/bulk",
        json={"ids": [draft_id, ready_id], "action": "delete"},
    )
    assert delete.status_code == 200
    del_result = delete.json()
    assert del_result["succeeded"] == [draft_id]
    assert del_result["failed"][0]["id"] == ready_id

    enqueue = client.post(
        "/api/content/variants/bulk",
        json={"ids": [ready_id, no_account_id], "action": "enqueue"},
    )
    assert enqueue.status_code == 200
    enq_result = enqueue.json()
    assert ready_id in enq_result["succeeded"]
    assert any(f["id"] == no_account_id for f in enq_result["failed"])


def test_llm_bulk_enable_disable_delete(client: TestClient):
    db = SessionLocal()
    try:
        m1 = llm_model_service.create(
            db,
            alias="A",
            provider="openai",
            model="gpt-test",
            enabled=True,
        )
        m2 = llm_model_service.create(
            db,
            alias="B",
            provider="openai",
            model="gpt-test-2",
            enabled=True,
        )
        m1_id, m2_id = m1.id, m2.id
    finally:
        db.close()

    disable = client.post(
        "/api/llm/models/bulk",
        json={"ids": [m1_id, m2_id], "action": "disable"},
    )
    assert disable.status_code == 200
    assert set(disable.json()["succeeded"]) == {m1_id, m2_id}

    enable = client.post(
        "/api/llm/models/bulk",
        json={"ids": [m1_id], "action": "enable"},
    )
    assert enable.status_code == 200
    models = {m["id"]: m["enabled"] for m in client.get("/api/llm/models").json()}
    assert models[m1_id] is True
    assert models[m2_id] is False

    delete = client.post(
        "/api/llm/models/bulk",
        json={"ids": [m1_id, 424242], "action": "delete"},
    )
    assert delete.status_code == 200
    result = delete.json()
    assert m1_id in result["succeeded"]
    assert result["failed"][0]["id"] == 424242


def test_jobs_bulk_cancel_retry(client: TestClient):
    db = SessionLocal()
    try:
        account = _seed_account(db, name="jobber", active=True)
        variant = _seed_variant(db, account, status="READY")
        pending = job_service.create(
            db,
            content_variant_id=variant.id,
            account_id=account.id,
            scheduled_at=datetime.utcnow(),
        )
        failed = job_service.create(
            db,
            content_variant_id=variant.id,
            account_id=account.id,
            scheduled_at=datetime.utcnow(),
        )
        failed.status = JobStatus.FAILED.value
        failed.error_message = "boom"
        db.commit()
        db.refresh(failed)
        pending_id, failed_id = pending.id, failed.id
    finally:
        db.close()

    cancel = client.post(
        "/api/jobs/bulk-actions",
        json={"ids": [pending_id], "action": "cancel"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["succeeded"] == [pending_id]
    cancelled = client.get(f"/api/jobs/{pending_id}").json()
    assert cancelled["status"] == JobStatus.CANCELLED.value

    retry = client.post(
        "/api/jobs/bulk-actions",
        json={"ids": [failed_id, 99999], "action": "retry"},
    )
    assert retry.status_code == 200
    retry_result = retry.json()
    assert failed_id in retry_result["succeeded"]
    assert retry_result["failed"][0]["id"] == 99999
    retried = client.get(f"/api/jobs/{failed_id}").json()
    assert retried["status"] == JobStatus.PENDING.value


def test_jobs_bulk_invalid_action(client: TestClient):
    resp = client.post("/api/jobs/bulk-actions", json={"ids": [1], "action": "delete"})
    assert resp.status_code == 400
