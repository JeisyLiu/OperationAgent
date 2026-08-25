import pytest

from app.platforms import get_platform, is_publishable, list_platforms, require_platform
from app.platforms.loader import PlatformDisabledError, PlatformNotFoundError


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


def test_bilibili_not_publishable_yet():
    assert get_platform("bilibili") is not None
    assert is_publishable("bilibili") is False
