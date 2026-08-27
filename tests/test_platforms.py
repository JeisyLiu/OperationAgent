import pytest
from fastapi.testclient import TestClient

from app.db.models import Base
from app.db.session import engine
from app.main import app
from app.platforms import get_platform, is_publishable, list_platforms, require_platform
from app.platforms.loader import PlatformDisabledError, PlatformNotFoundError, clear_platform_cache
from tests.conftest import safe_drop_all


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    safe_drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_list_platforms_includes_tiktok():
    platforms = list_platforms(enabled_only=True)
    ids = {p.id for p in platforms}
    assert "tiktok" in ids
    assert "bilibili" in ids
    assert "twitter" in ids
    assert "douyin" in ids
    assert "kuaishou" in ids
    assert "zhihu" in ids
    assert "weibo" in ids
    assert "instagram" in ids


def test_list_platforms_includes_new_builtin_platforms():
    platforms = list_platforms(enabled_only=True)
    ids = {p.id for p in platforms}
    for pid in ("discord", "telegram", "linkedin", "threads"):
        assert pid in ids


def test_new_platforms_have_expected_media_types():
    discord = get_platform("discord")
    linkedin = get_platform("linkedin")
    assert discord is not None
    assert linkedin is not None
    assert "text" in discord.media_types
    assert "text" in linkedin.media_types
    assert discord.channel is None
    assert discord.source == "builtin"


def test_discord_publish_options_target():
    platform = get_platform("discord")
    assert platform is not None
    choices = platform.publish_options.get("target", {}).get("choices", [])
    assert len(choices) >= 2


def test_require_platform_unknown():
    with pytest.raises(PlatformNotFoundError):
        require_platform("not-a-platform")


def test_tiktok_is_publishable():
    assert is_publishable("tiktok") is True


def test_all_platforms_have_default_skill():
    for platform in list_platforms(enabled_only=False):
        assert platform.default_persona, f"{platform.id} missing default_persona"
        assert platform.default_skill.get("tone"), f"{platform.id} missing default_skill.tone"
        assert platform.default_skill.get("language"), f"{platform.id} missing default_skill.language"


def test_bilibili_has_section_choices():
    platform = get_platform("bilibili")
    assert platform is not None
    choices = platform.publish_options.get("section", {}).get("choices", [])
    assert len(choices) >= 3


def test_tiktok_has_no_section_choices():
    platform = get_platform("tiktok")
    assert platform is not None
    choices = platform.publish_options.get("section", {}).get("choices", [])
    assert choices == []


def test_bilibili_is_publishable():
    assert get_platform("bilibili") is not None
    assert is_publishable("bilibili") is True


def test_rednote_is_publishable():
    assert is_publishable("rednote") is True


def test_rednote_preferred_adapter():
    platform = get_platform("rednote")
    assert platform is not None
    assert platform.preferred_adapter == "chrome_devtools"


def test_custom_platform_crud(client: TestClient):
    create = client.post(
        "/api/platforms",
        json={
            "id": "my_forum",
            "display_name": "My Forum",
            "home_url": "https://forum.example.com/",
            "default_skill": {"tone": "friendly", "language": "en"},
        },
    )
    assert create.status_code == 200
    data = create.json()
    assert data["id"] == "my_forum"
    assert data["source"] == "custom"

    listed = client.get("/api/platforms")
    assert listed.status_code == 200
    ids = {p["id"] for p in listed.json()}
    assert "my_forum" in ids

    patch = client.patch(
        "/api/platforms/my_forum",
        json={"display_name": "My Forum Updated"},
    )
    assert patch.status_code == 200
    assert patch.json()["display_name"] == "My Forum Updated"

    delete = client.delete("/api/platforms/my_forum")
    assert delete.status_code == 200
    clear_platform_cache()


def test_custom_platform_id_conflicts_with_builtin(client: TestClient):
    resp = client.post(
        "/api/platforms",
        json={
            "id": "tiktok",
            "display_name": "Fake TikTok",
            "home_url": "https://example.com/",
            "default_skill": {"tone": "x", "language": "en"},
        },
    )
    assert resp.status_code == 400


def test_delete_builtin_platform_fails(client: TestClient):
    resp = client.delete("/api/platforms/tiktok")
    assert resp.status_code == 400


def test_delete_custom_platform_with_account_fails(client: TestClient):
    create_platform = client.post(
        "/api/platforms",
        json={
            "id": "used_forum",
            "display_name": "Used Forum",
            "home_url": "https://used.example.com/",
            "default_skill": {"tone": "neutral", "language": "en"},
        },
    )
    assert create_platform.status_code == 200

    create_account = client.post(
        "/api/accounts",
        json={"platform": "used_forum", "account_name": "forum-user"},
    )
    assert create_account.status_code == 200

    delete = client.delete("/api/platforms/used_forum")
    assert delete.status_code == 400
    clear_platform_cache()
