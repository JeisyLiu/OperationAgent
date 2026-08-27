import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

PLATFORMS_DIR = Path(__file__).resolve().parent

PLATFORM_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


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
    preferred_adapter: str | None = None
    source: Literal["builtin", "custom"] = "builtin"

    @property
    def open_url(self) -> str:
        return self.login_url or self.home_url


class PlatformNotFoundError(ValueError):
    pass


class PlatformDisabledError(ValueError):
    pass


def _parse_platform(data: dict[str, Any], *, source: Literal["builtin", "custom"] = "builtin") -> PlatformDef:
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
        preferred_adapter=data.get("preferred_adapter"),
        source=source,
    )


@lru_cache
def _load_builtin() -> dict[str, PlatformDef]:
    platforms: dict[str, PlatformDef] = {}
    for path in sorted(PLATFORMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        platform = _parse_platform(raw, source="builtin")
        if platform.id != path.stem:
            raise ValueError(f"Platform id mismatch in {path.name}: {platform.id}")
        platforms[platform.id] = platform
    return platforms


def clear_platform_cache() -> None:
    _load_builtin.cache_clear()


def is_builtin_platform(platform_id: str) -> bool:
    return platform_id.lower() in _load_builtin()


def _custom_row_to_def(row) -> PlatformDef:
    return PlatformDef(
        id=row.id,
        display_name=row.display_name,
        region=row.region or "global",
        home_url=row.home_url,
        login_url=row.login_url or row.home_url,
        upload_url=row.upload_url or row.home_url,
        enabled=bool(row.enabled),
        channel=None,
        media_types=json.loads(row.media_types_json or "[]"),
        variant_schema=json.loads(row.variant_schema_json or "{}"),
        session={},
        default_persona=row.default_persona,
        default_skill=json.loads(row.default_skill_json or "{}"),
        publish_options=json.loads(row.publish_options_json or "{}"),
        preferred_adapter=row.preferred_adapter,
        source="custom",
    )


def _load_custom(db: Session) -> dict[str, PlatformDef]:
    from sqlalchemy.exc import OperationalError

    from app.db.models import CustomPlatform

    try:
        rows = db.query(CustomPlatform).all()
    except OperationalError:
        return {}
    return {row.id: _custom_row_to_def(row) for row in rows}


def _resolve_db(db: Session | None):
    if db is not None:
        return db, False
    from app.db.session import SessionLocal

    return SessionLocal(), True


def list_platforms(*, enabled_only: bool = False, db: Session | None = None) -> list[PlatformDef]:
    merged = dict(_load_builtin())
    session, owned = _resolve_db(db)
    try:
        for pid, platform in _load_custom(session).items():
            if pid not in merged:
                merged[pid] = platform
    finally:
        if owned:
            session.close()

    items = list(merged.values())
    if enabled_only:
        items = [p for p in items if p.enabled]
    return sorted(items, key=lambda p: p.display_name.lower())


def get_platform(platform_id: str, db: Session | None = None) -> PlatformDef | None:
    if not platform_id:
        return None
    pid = platform_id.lower()
    builtin = _load_builtin().get(pid)
    if builtin is not None:
        return builtin

    session, owned = _resolve_db(db)
    try:
        return _load_custom(session).get(pid)
    finally:
        if owned:
            session.close()


def require_platform(platform_id: str, db: Session | None = None) -> PlatformDef:
    platform = get_platform(platform_id, db=db)
    if platform is None:
        raise PlatformNotFoundError(f"Unknown platform: {platform_id}")
    if not platform.enabled:
        raise PlatformDisabledError(f"Platform is disabled: {platform_id}")
    return platform


def has_channel(platform_id: str, db: Session | None = None) -> bool:
    from app.channels.registry import has_channel as registry_has_channel

    platform = get_platform(platform_id, db=db)
    if platform is None or not platform.channel:
        return False
    return registry_has_channel(platform.channel)


def is_publishable(platform_id: str, db: Session | None = None) -> bool:
    platform = get_platform(platform_id, db=db)
    if platform is None:
        return False
    return platform.enabled


def get_open_url(platform_id: str, db: Session | None = None) -> str:
    return require_platform(platform_id, db=db).open_url


def get_platform_default_skill(platform_id: str, db: Session | None = None) -> dict[str, Any]:
    platform = get_platform(platform_id, db=db)
    if platform is None:
        return {}
    return dict(platform.default_skill)


def get_platform_default_persona(platform_id: str, db: Session | None = None) -> str | None:
    platform = get_platform(platform_id, db=db)
    if platform is None:
        return None
    return platform.default_persona
