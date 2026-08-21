import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(os.environ['APP_DATA_DIR']) / 'test.db'}")

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.crypto import decrypt_text, encrypt_text, mask_api_key
from app.services.settings_service import settings_service


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_encrypt_decrypt_roundtrip():
    plain = "sk-test-secret-key-12345"
    cipher = encrypt_text(plain)
    assert decrypt_text(cipher) == plain
    assert plain not in cipher


def test_mask_api_key():
    masked = mask_api_key("sk-abcdefghijklmnop")
    assert masked is not None
    assert "abcdefghijklmnop" not in masked
    assert "***" in masked


def test_settings_save_and_public(db: Session):
    settings_service.save(
        db,
        provider="openai",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        api_key="sk-secret-value",
    )
    public = settings_service.get_public(db)
    assert public is not None
    assert public.provider == "openai"
    assert public.api_key_masked is not None
    assert "secret-value" not in (public.api_key_masked or "")


def test_settings_api(client: TestClient):
    put_resp = client.put(
        "/api/settings/ai",
        json={
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-test",
            "api_key": "sk-test-key-abcdef",
        },
    )
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["provider"] == "openai"
    assert "abcdef" not in (body.get("api_key") or body.get("api_key", ""))

    get_resp = client.get("/api/settings/ai")
    assert get_resp.status_code == 200
    assert get_resp.json()["model"] == "gpt-test"


def test_health_version(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.1.6"
