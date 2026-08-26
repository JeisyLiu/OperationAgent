import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")

from app.db.models import AiSettings, Base, LlmModel
from app.db.session import SessionLocal, engine
from app.llm.gateway import LlmGateway
from app.llm.types import BatchItem, BatchResult, ChatResult
from app.main import app
from app.services.crypto import encrypt_text
from app.services.llm_model_service import llm_model_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_models(db):
    primary = llm_model_service.create(
        db,
        alias="Primary",
        provider="openai",
        model="gpt-test",
        api_key="key-1",
        enabled=True,
        priority=0,
    )
    backup = llm_model_service.create(
        db,
        alias="Backup",
        provider="qwen",
        model="qwen-turbo",
        api_key="key-2",
        enabled=True,
        priority=1,
    )
    return primary, backup


def test_llm_models_crud(client: TestClient):
    create = client.post(
        "/api/llm/models",
        json={
            "alias": "OpenAI main",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "priority": 0,
        },
    )
    assert create.status_code == 200
    model_id = create.json()["id"]

    listing = client.get("/api/llm/models")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    patch = client.patch(f"/api/llm/models/{model_id}", json={"alias": "Renamed", "enabled": False})
    assert patch.status_code == 200
    assert patch.json()["alias"] == "Renamed"
    assert patch.json()["enabled"] is False

    delete = client.delete(f"/api/llm/models/{model_id}")
    assert delete.status_code == 200
    assert client.get("/api/llm/models").json() == []


def test_migrate_ai_settings_to_llm_models():
    from app.db.migrate import _migrate_ai_settings_to_llm_models

    db = SessionLocal()
    try:
        db.add(
            AiSettings(
                provider="openai",
                base_url="https://api.example.com/v1",
                model="gpt-legacy",
                api_key_enc=encrypt_text("legacy-key"),
            )
        )
        db.commit()
        _migrate_ai_settings_to_llm_models()
        rows = db.query(LlmModel).all()
        assert len(rows) == 1
        assert rows[0].alias == "Default"
        assert rows[0].model == "gpt-legacy"
    finally:
        db.close()


@patch("app.llm.gateway.pool.get_adapter")
def test_gateway_failover(mock_get_adapter):
    db = SessionLocal()
    try:
        _seed_models(db)
    finally:
        db.close()

    primary_adapter = MagicMock()
    backup_adapter = MagicMock()
    primary_adapter.chat.side_effect = RuntimeError("primary down")
    backup_adapter.chat.return_value = ChatResult(text="ok-from-backup")

    def _adapter(provider):
        if provider == "openai":
            return primary_adapter
        return backup_adapter

    mock_get_adapter.side_effect = _adapter

    gateway = LlmGateway()
    text = gateway.chat([{"role": "user", "content": "hi"}], max_tokens=32)
    assert text == "ok-from-backup"
    backup_adapter.chat.assert_called_once()


@patch("app.llm.gateway.LlmGateway.chat")
def test_chat_batch_partial_failure(mock_chat):
    gateway = LlmGateway()

    def _side_effect(messages, **kwargs):
        if messages[0]["content"] == "bad":
            raise RuntimeError("boom")
        return "ok"

    mock_chat.side_effect = _side_effect
    results = gateway.chat_batch(
        [
            BatchItem(key=1, messages=[{"role": "user", "content": "good"}]),
            BatchItem(key=2, messages=[{"role": "user", "content": "bad"}]),
        ],
        max_tokens=16,
        max_workers=2,
    )
    by_key = {r.key: r for r in results}
    assert by_key[1].ok is True
    assert by_key[2].ok is False


def test_no_enabled_models_raises():
    gateway = LlmGateway()
    with pytest.raises(ValueError, match="No enabled LLM model"):
        gateway.chat([{"role": "user", "content": "hi"}])
