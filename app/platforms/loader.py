import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PLATFORMS_DIR = Path(__file__).resolve().parent


@dataclass
class PlatformDef:
    id: str
    display_name: str
    region: str
    home_url: str
    login_url: str
    upload_url: str
    enabled: bool
    channel: str | None
    media_types: list[str] = field(default_factory=list)
    variant_schema: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    default_persona: str | None = None
    default_skill: dict[str, Any] = field(default_factory=dict)
    publish_options: dict[str, Any] = field(default_factory=dict)

    @property
    def open_url(self) -> str:
        return self.login_url or self.home_url


class PlatformNotFoundError(ValueError):
    pass


class PlatformDisabledError(ValueError):
    pass


def _parse_platform(data: dict[str, Any]) -> PlatformDef:
    return PlatformDef(
        id=data["id"],
        display_name=data["display_name"],
        region=data.get("region", "global"),
        home_url=data["home_url"],
        login_url=data.get("login_url", data["home_url"]),
        upload_url=data.get("upload_url", data["home_url"]),
        enabled=bool(data.get("enabled", True)),
        channel=data.get("channel"),
        media_types=list(data.get("media_types", [])),
        variant_schema=dict(data.get("variant_schema", {})),
        session=dict(data.get("session", {})),
        default_persona=data.get("default_persona"),
        default_skill=dict(data.get("default_skill", {})),
        publish_options=dict(data.get("publish_options", {})),
    )


@lru_cache
def _load_all() -> dict[str, PlatformDef]:
    platforms: dict[str, PlatformDef] = {}
    for path in sorted(PLATFORMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        platform = _parse_platform(raw)
        if platform.id != path.stem:
            raise ValueError(f"Platform id mismatch in {path.name}: {platform.id}")
        platforms[platform.id] = platform
    return platforms


def list_platforms(*, enabled_only: bool = False) -> list[PlatformDef]:
    items = list(_load_all().values())
    if enabled_only:
        items = [p for p in items if p.enabled]
    return sorted(items, key=lambda p: p.display_name.lower())


def get_platform(platform_id: str) -> PlatformDef | None:
    if not platform_id:
        return None
    return _load_all().get(platform_id.lower())


def require_platform(platform_id: str) -> PlatformDef:
    platform = get_platform(platform_id)
    if platform is None:
        raise PlatformNotFoundError(f"Unknown platform: {platform_id}")
    if not platform.enabled:
        raise PlatformDisabledError(f"Platform is disabled: {platform_id}")
    return platform


def has_channel(platform_id: str) -> bool:
    from app.channels.registry import has_channel as registry_has_channel

    platform = get_platform(platform_id)
    if platform is None or not platform.channel:
        return False
    return registry_has_channel(platform.channel)


def is_publishable(platform_id: str) -> bool:
    platform = get_platform(platform_id)
    if platform is None or not platform.enabled or not platform.channel:
        return False
    return has_channel(platform_id)


def get_open_url(platform_id: str) -> str:
    return require_platform(platform_id).open_url


def get_platform_default_skill(platform_id: str) -> dict[str, Any]:
    platform = get_platform(platform_id)
    if platform is None:
        return {}
    return dict(platform.default_skill)


def get_platform_default_persona(platform_id: str) -> str | None:
    platform = get_platform(platform_id)
    if platform is None:
        return None
    return platform.default_persona
