import json
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
from app.services.account_service import account_service
from app.services.skill_seed import seed_skill_templates
from app.skills.loader import get_overlay, get_role, list_roles_from_files


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_list_skill_roles(client: TestClient):
    resp = client.get("/api/skills/roles")
    assert resp.status_code == 200
    roles = resp.json()
    assert len(roles) >= 14
    assert any(r["id"] == "product_recommender" for r in roles)
    assert any(r["id"] == "community_ops" for r in roles)
    assert any(r["id"] == "recruiter" for r in roles)


def test_list_skill_tags(client: TestClient):
    resp = client.get("/api/skills/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert any(t["id"] == "digital" for t in tags)


def test_role_preview_differs_by_platform(client: TestClient):
    rednote = client.get(
        "/api/skills/roles/product_recommender/preview",
        params={"platform": "rednote"},
    )
    tiktok = client.get(
        "/api/skills/roles/product_recommender/preview",
        params={"platform": "tiktok"},
    )
    assert rednote.status_code == 200
    assert tiktok.status_code == 200
    assert rednote.json()["skill"]["language"] == "zh-CN"
    assert tiktok.json()["skill"]["language"] == "en"


def test_account_create_with_role(client: TestClient):
    resp = client.post(
        "/api/accounts",
        json={
            "platform": "rednote",
            "account_name": "种草号",
            "role_id": "product_recommender",
            "role_tags": ["soft_sell"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role_id"] == "product_recommender"
    assert "soft_sell" in data["role_tags"]
    assert data["role_display_name"] == "好物推荐官"
    assert data["skill"]["tone"]
    assert data["skill"]["topics"]


def test_account_create_rejects_unknown_role(client: TestClient):
    resp = client.post(
        "/api/accounts",
        json={"platform": "tiktok", "account_name": "x", "role_id": "not_a_role"},
    )
    assert resp.status_code == 400


def test_account_skill_override_wins(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={
            "platform": "tiktok",
            "account_name": "override",
            "role_id": "product_recommender",
            "skill": {"tone": "my-custom-tone"},
        },
    )
    assert create.status_code == 200
    data = create.json()
    assert data["skill"]["tone"] == "my-custom-tone"


def test_clear_skill_override_restores_template(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={
            "platform": "tiktok",
            "account_name": "reset-me",
            "role_id": "product_recommender",
            "skill": {"tone": "custom-only"},
        },
    )
    account_id = create.json()["id"]
    patch = client.patch(f"/api/accounts/{account_id}", json={"clear_skill_override": True})
    assert patch.status_code == 200
    assert patch.json()["skill"]["tone"] != "custom-only"


def test_bulk_set_role(client: TestClient):
    create = client.post(
        "/api/accounts",
        json={"platform": "tiktok", "account_name": "bulk-role"},
    )
    account_id = create.json()["id"]
    bulk = client.post(
        "/api/accounts/bulk",
        json={
            "ids": [account_id],
            "action": "set_role",
            "role_id": "news_media",
            "replace_skill": True,
        },
    )
    assert bulk.status_code == 200
    assert bulk.json()["succeeded"] == [account_id]
    account = client.get(f"/api/accounts/{account_id}").json()
    assert account["role_id"] == "news_media"


def test_role_preview_differs_discord_vs_linkedin(client: TestClient):
    community_discord = client.get(
        "/api/skills/roles/community_ops/preview",
        params={"platform": "discord"},
    )
    recruiter_linkedin = client.get(
        "/api/skills/roles/recruiter/preview",
        params={"platform": "linkedin"},
    )
    assert community_discord.status_code == 200
    assert recruiter_linkedin.status_code == 200
    c_skill = community_discord.json()["skill"]
    r_skill = recruiter_linkedin.json()["skill"]
    assert c_skill.get("tone") != r_skill.get("tone")
    assert "Discord" in (community_discord.json().get("persona") or "")
    assert "LinkedIn" in (recruiter_linkedin.json().get("persona") or "")


def test_list_skill_tags_includes_new_topics(client: TestClient):
    resp = client.get("/api/skills/tags")
    assert resp.status_code == 200
    tag_ids = {t["id"] for t in resp.json()}
    for tid in ("gaming", "saas", "b2b", "finance", "food", "travel"):
        assert tid in tag_ids


def test_db_seed_and_override_file(client: TestClient):
    db = SessionLocal()
    try:
        first = seed_skill_templates(db)
        assert first >= 14
        role = get_role("educator", db)
        assert role is not None
        assert role.display_name == "干货/教学号"
    finally:
        db.close()


def test_seed_skips_existing_and_fills_missing(client: TestClient):
    from app.db.models import SkillRole, SkillRoleOverlay

    db = SessionLocal()
    try:
        seed_skill_templates(db)
        row = db.query(SkillRole).filter(SkillRole.id == "product_recommender").first()
        assert row is not None
        row.display_name = "用户自定义推荐官"
        row.skill_json = json.dumps({"tone": "user-custom-tone"}, ensure_ascii=False)
        overlay = (
            db.query(SkillRoleOverlay)
            .filter(
                SkillRoleOverlay.role_id == "product_recommender",
                SkillRoleOverlay.platform == "bilibili",
            )
            .first()
        )
        assert overlay is not None
        overlay.persona_suffix = "，用户自定义后缀"
        db.commit()

        # Simulate a missing overlay row (e.g. newly added platform JSON)
        missing = (
            db.query(SkillRoleOverlay)
            .filter(
                SkillRoleOverlay.role_id == "product_recommender",
                SkillRoleOverlay.platform == "tiktok",
            )
            .first()
        )
        if missing is not None:
            db.delete(missing)
            db.commit()

        again = seed_skill_templates(db)
        assert again >= 1

        row = db.query(SkillRole).filter(SkillRole.id == "product_recommender").first()
        assert row.display_name == "用户自定义推荐官"
        assert "user-custom-tone" in (row.skill_json or "")

        overlay = (
            db.query(SkillRoleOverlay)
            .filter(
                SkillRoleOverlay.role_id == "product_recommender",
                SkillRoleOverlay.platform == "bilibili",
            )
            .first()
        )
        assert overlay.persona_suffix == "，用户自定义后缀"

        restored = (
            db.query(SkillRoleOverlay)
            .filter(
                SkillRoleOverlay.role_id == "product_recommender",
                SkillRoleOverlay.platform == "tiktok",
            )
            .first()
        )
        assert restored is not None

        # Fully seeded: second pass inserts nothing
        assert seed_skill_templates(db) == 0
    finally:
        db.close()


def test_get_overlay_differs_by_platform(client: TestClient):
    bili = client.get("/api/skills/roles/product_recommender/overlays/bilibili")
    tiktok = client.get("/api/skills/roles/product_recommender/overlays/tiktok")
    assert bili.status_code == 200
    assert tiktok.status_code == 200
    assert bili.json()["exists"] is True
    assert tiktok.json()["exists"] is True
    assert bili.json()["skill"]["language"] == "zh-CN"
    assert tiktok.json()["skill"]["language"] == "en"
    assert bili.json()["skill"] != tiktok.json()["skill"]


def test_generate_prompt_includes_claim_policy(client: TestClient):
    from app.services.content_generate_service import content_generate_service

    template = content_generate_service._load_prompt_template()
    assert "claim_policy" in template
    assert "structure" in template
