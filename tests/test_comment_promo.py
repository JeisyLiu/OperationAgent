import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")
os.environ.setdefault("AGENT_ADAPTER", "mock")

from app.db.models import Base, ExecutionLog, OperationRun, OperationStep, PromoComment, PromoRun, PromoSeenUrl, PromoTarget
from app.services.execution_log_service import SUBJECT_PROMO_RUN
from tests.conftest import safe_drop_all
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.account_service import account_service
from app.services.content_service import content_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_bilibili_variant(db, *, with_tags: bool = True):
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
    tags = ["教程", "测评"] if with_tags else []
    asset = content_service.create_asset(
        db,
        title="母帖",
        base_caption="base",
        media_type="text",
        tags=tags,
    )
    variant = content_service.create_variant(
        db,
        asset_id=asset.id,
        platform="bilibili",
        title="pkg",
        caption="cap",
        extra={
            "account_id": account.id,
            "generated_by": "skill",
            "account_name": account.account_name,
        },
    )
    return account, asset, variant


MOCK_DISCOVER_ITEMS = [
    {
        "url": "https://www.bilibili.com/video/BV1",
        "title": "视频一",
        "description": "描述一",
    },
    {
        "url": "https://www.bilibili.com/video/BV2",
        "title": "视频二",
        "description": "描述二",
    },
    {
        "url": "https://www.bilibili.com/video/BV3",
        "title": "视频三",
        "description": "描述三",
    },
    {
        "url": "https://www.bilibili.com/video/BV4",
        "title": "视频四",
        "description": "描述四",
    },
    {
        "url": "https://www.bilibili.com/video/BV5",
        "title": "视频五",
        "description": "描述五",
    },
]


async def _mock_discover_by_tag(db, run, account, tag, on_step):
    prefix = "教程" if tag == "教程" else "测评"
    return [
        {
            "url": f"https://www.bilibili.com/video/{prefix}-BV{i}",
            "title": f"{tag}视频{i}",
            "description": f"描述{i}",
        }
        for i in range(1, 6)
    ]


def test_promo_requires_tags(client: TestClient):
    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=False)
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert resp.status_code == 400
    assert "标签" in resp.json()["detail"]


def test_promo_rejects_tiktok(client: TestClient):
    db = SessionLocal()
    try:
        account = account_service.create(db, platform="tiktok", account_name="t1")
        account_service.mark_active(db, account)
        asset = content_service.create_asset(
            db, title="v", base_caption="b", media_type="text", tags=["ai"]
        )
        variant = content_service.create_variant(
            db,
            asset_id=asset.id,
            platform="tiktok",
            title="t",
            caption="c",
            extra={"account_id": account.id, "generated_by": "skill"},
        )
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert resp.status_code == 400
    assert "小红书" in resp.json()["detail"] or "B 站" in resp.json()["detail"]


@patch("app.services.comment_promo_service.llm.chat_with_usage")
@patch(
    "app.services.comment_promo_service.CommentPromoService._discover_for_tag",
    new_callable=AsyncMock,
)
def test_promo_pipeline_creates_comments(mock_discover, mock_llm, client: TestClient):
    mock_discover.side_effect = _mock_discover_by_tag

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 20
        total_tokens = 30

    mock_llm.return_value = type(
        "R",
        (),
        {
            "text": json.dumps({"comments": [f"评论{i}" for i in range(1, 6)]}),
            "usage": FakeUsage(),
            "model_id": 1,
            "model_alias": "Test",
        },
    )()

    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=True)
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert resp.status_code == 200
    run_id = resp.json()["id"]
    assert resp.json().get("operation_run_id")

    import time

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{run_id}").json()
        if detail["status"] in ("ready", "partial", "failed"):
            break
        time.sleep(0.1)

    detail = client.get(f"/api/promo/runs/{run_id}").json()
    assert detail["status"] in ("ready", "partial")
    assert len(detail["targets"]) == 10  # 2 tags x 5 videos

    db = SessionLocal()
    try:
        comments = db.query(PromoComment).filter(PromoComment.run_id == run_id).all()
        assert len(comments) == 50  # 10 targets x 5 comments
        ops = db.query(OperationRun).filter(OperationRun.kind == "promo").all()
        assert len(ops) == 1
        assert ops[0].status in ("success", "partial")
        assert ops[0].total_tokens is not None and ops[0].total_tokens > 0
        steps = db.query(OperationStep).filter(OperationStep.run_id == ops[0].id).all()
        assert len(steps) >= 12  # 2 discover + 10 generate
    finally:
        db.close()

    history = client.get("/api/history")
    assert history.status_code == 200
    kinds = {item["kind"] for item in history.json()["items"]}
    assert "promo" in kinds

    op_id = detail["operation_run_id"]
    op_detail = client.get(f"/api/operations/{op_id}")
    assert op_detail.status_code == 200
    assert op_detail.json()["kind"] == "promo"
    assert len(op_detail.json()["steps"]) >= 1

    listing = client.get(f"/api/promo/runs?variant_id={variant_id}")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    first_comment = detail["targets"][0]["comments"][0]
    patch = client.patch(
        f"/api/promo/comments/{first_comment['id']}",
        json={"body": "修改后的评论"},
    )
    assert patch.status_code == 200
    assert patch.json()["body"] == "修改后的评论"

    delete = client.delete(f"/api/promo/comments/{first_comment['id']}")
    assert delete.status_code == 200


@patch("app.services.comment_promo_service.llm.chat_with_usage")
@patch(
    "app.services.comment_promo_service.CommentPromoService._discover_for_tag",
    new_callable=AsyncMock,
)
def test_promo_writes_execution_logs(mock_discover, mock_llm, client: TestClient):
    mock_discover.side_effect = _mock_discover_by_tag

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 20
        total_tokens = 30

    mock_llm.return_value = type(
        "R",
        (),
        {
            "text": json.dumps({"comments": [f"评论{i}" for i in range(1, 6)]}),
            "usage": FakeUsage(),
            "model_id": 1,
            "model_alias": "Test",
        },
    )()

    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=True)
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert resp.status_code == 200
    run_id = resp.json()["id"]

    import time

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{run_id}").json()
        if detail["status"] in ("ready", "partial", "failed", "cancelled"):
            break
        time.sleep(0.1)

    detail = client.get(f"/api/promo/runs/{run_id}").json()
    assert detail["logs"]
    assert any(log["step"] == "discover-start" for log in detail["logs"])
    assert any(log["step"] == "url-found" for log in detail["logs"])

    db = SessionLocal()
    try:
        logs = (
            db.query(ExecutionLog)
            .filter(
                ExecutionLog.subject_type == SUBJECT_PROMO_RUN,
                ExecutionLog.subject_id == run_id,
            )
            .all()
        )
        assert logs
        assert all(log.subject_type == SUBJECT_PROMO_RUN for log in logs)
    finally:
        db.close()


@patch("app.services.comment_promo_service.llm.chat_with_usage")
@patch(
    "app.services.comment_promo_service.CommentPromoService._discover_for_tag",
    new_callable=AsyncMock,
)
def test_promo_seen_urls_skip_second_run(mock_discover, mock_llm, client: TestClient):
    mock_discover.side_effect = _mock_discover_by_tag

    class FakeUsage:
        prompt_tokens = 5
        completion_tokens = 5
        total_tokens = 10

    mock_llm.return_value = type(
        "R",
        (),
        {
            "text": json.dumps({"comments": [f"评论{i}" for i in range(1, 6)]}),
            "usage": FakeUsage(),
            "model_id": 1,
            "model_alias": "Test",
        },
    )()

    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=True)
        variant_id = variant.id
    finally:
        db.close()

    first = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert first.status_code == 200
    first_id = first.json()["id"]

    import time

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{first_id}").json()
        if detail["status"] in ("ready", "partial", "failed"):
            break
        time.sleep(0.1)

    first_detail = client.get(f"/api/promo/runs/{first_id}").json()
    assert len(first_detail["targets"]) == 10

    db = SessionLocal()
    try:
        seen_count = db.query(PromoSeenUrl).count()
        assert seen_count >= 10
    finally:
        db.close()

    second = client.post("/api/promo/runs", json={"variant_id": variant_id})
    assert second.status_code == 200
    second_id = second.json()["id"]

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{second_id}").json()
        if detail["status"] in ("ready", "partial", "failed", "cancelled"):
            break
        time.sleep(0.1)

    second_detail = client.get(f"/api/promo/runs/{second_id}").json()
    assert second_detail["status"] == "failed"
    assert second_detail.get("error_message") == "未发现任何视频"
    assert any(log["step"] == "url-skipped" for log in second_detail["logs"])


@patch("app.services.comment_promo_service.llm.chat_with_usage")
@patch(
    "app.services.comment_promo_service.CommentPromoService._discover_for_tag",
    new_callable=AsyncMock,
)
def test_promo_abort_endpoint(mock_discover, mock_llm, client: TestClient):
    async def slow_discover(db, run, account, tag, on_step):
        import asyncio

        await asyncio.sleep(0.3)
        return await _mock_discover_by_tag(db, run, account, tag, on_step)

    mock_discover.side_effect = slow_discover

    class FakeUsage:
        prompt_tokens = 5
        completion_tokens = 5
        total_tokens = 10

    mock_llm.return_value = type(
        "R",
        (),
        {
            "text": json.dumps({"comments": [f"评论{i}" for i in range(1, 6)]}),
            "usage": FakeUsage(),
            "model_id": 1,
            "model_alias": "Test",
        },
    )()

    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=True)
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    run_id = resp.json()["id"]

    import time

    time.sleep(0.05)
    abort = client.post(f"/api/promo/runs/{run_id}/abort")
    assert abort.status_code == 200
    assert abort.json()["status"] == "cancelling"

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{run_id}").json()
        if detail["status"] == "cancelled":
            break
        time.sleep(0.1)

    detail = client.get(f"/api/promo/runs/{run_id}").json()
    assert detail["status"] == "cancelled"
    assert any(log["step"] == "abort-requested" for log in detail["logs"])


@patch("app.services.comment_promo_service.llm.chat_with_usage")
@patch(
    "app.services.comment_promo_service.CommentPromoService._discover_for_tag",
    new_callable=AsyncMock,
)
def test_promo_logs_since_id(mock_discover, mock_llm, client: TestClient):
    async def one_item(db, run, account, tag, on_step):
        return (await _mock_discover_by_tag(db, run, account, tag, on_step))[:1]

    mock_discover.side_effect = one_item

    class FakeUsage:
        prompt_tokens = 5
        completion_tokens = 5
        total_tokens = 10

    mock_llm.return_value = type(
        "R",
        (),
        {
            "text": json.dumps({"comments": [f"评论{i}" for i in range(1, 6)]}),
            "usage": FakeUsage(),
            "model_id": 1,
            "model_alias": "Test",
        },
    )()

    db = SessionLocal()
    try:
        _, _, variant = _seed_bilibili_variant(db, with_tags=True)
        variant_id = variant.id
    finally:
        db.close()

    resp = client.post("/api/promo/runs", json={"variant_id": variant_id})
    run_id = resp.json()["id"]

    import time

    for _ in range(50):
        detail = client.get(f"/api/promo/runs/{run_id}").json()
        if detail["status"] in ("ready", "partial", "failed"):
            break
        time.sleep(0.1)

    full = client.get(f"/api/promo/runs/{run_id}").json()
    logs = full["logs"]
    assert len(logs) >= 2
    mid = logs[0]["id"]
    inc = client.get(f"/api/promo/runs/{run_id}?since_id={mid}").json()
    assert all(log["id"] > mid for log in inc["logs"])
