import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Account, CustomPlatform
from app.platforms.loader import (
    PLATFORM_ID_RE,
    PlatformDef,
    _custom_row_to_def,
    clear_platform_cache,
    is_builtin_platform,
)


class PlatformConflictError(ValueError):
    pass


class PlatformInUseError(ValueError):
    pass


class PlatformNotCustomError(ValueError):
    pass


def validate_platform_id(platform_id: str) -> str:
    pid = (platform_id or "").strip().lower()
    if not PLATFORM_ID_RE.match(pid):
        raise ValueError(
            "Platform id must match ^[a-z][a-z0-9_]{1,31}$ (lowercase letters, digits, underscore)"
        )
    return pid


def create_custom_platform(db: Session, payload: dict[str, Any]) -> PlatformDef:
    pid = validate_platform_id(payload["id"])
    if is_builtin_platform(pid):
        raise PlatformConflictError(f"Platform id conflicts with builtin: {pid}")
    if db.query(CustomPlatform).filter(CustomPlatform.id == pid).first():
        raise PlatformConflictError(f"Platform already exists: {pid}")

    row = CustomPlatform(
        id=pid,
        display_name=payload["display_name"],
        region=payload.get("region") or "global",
        home_url=payload["home_url"],
        login_url=payload.get("login_url") or payload["home_url"],
        upload_url=payload.get("upload_url") or payload["home_url"],
        enabled=1 if payload.get("enabled", True) else 0,
        media_types_json=json.dumps(payload.get("media_types") or ["text"], ensure_ascii=False),
        variant_schema_json=json.dumps(payload.get("variant_schema") or {}, ensure_ascii=False),
        default_persona=payload.get("default_persona"),
        default_skill_json=json.dumps(payload.get("default_skill") or {}, ensure_ascii=False),
        publish_options_json=json.dumps(payload.get("publish_options") or {}, ensure_ascii=False),
        preferred_adapter=payload.get("preferred_adapter"),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    clear_platform_cache()
    return _custom_row_to_def(row)


def update_custom_platform(db: Session, platform_id: str, payload: dict[str, Any]) -> PlatformDef:
    pid = validate_platform_id(platform_id)
    if is_builtin_platform(pid):
        raise PlatformNotCustomError(f"Cannot modify builtin platform: {pid}")

    row = db.query(CustomPlatform).filter(CustomPlatform.id == pid).first()
    if row is None:
        raise ValueError(f"Unknown custom platform: {pid}")

    if "display_name" in payload and payload["display_name"] is not None:
        row.display_name = payload["display_name"]
    if "region" in payload and payload["region"] is not None:
        row.region = payload["region"]
    if "home_url" in payload and payload["home_url"] is not None:
        row.home_url = payload["home_url"]
    if "login_url" in payload:
        row.login_url = payload["login_url"] or row.home_url
    if "upload_url" in payload:
        row.upload_url = payload["upload_url"] or row.home_url
    if "enabled" in payload and payload["enabled"] is not None:
        row.enabled = 1 if payload["enabled"] else 0
    if "media_types" in payload and payload["media_types"] is not None:
        row.media_types_json = json.dumps(payload["media_types"], ensure_ascii=False)
    if "variant_schema" in payload and payload["variant_schema"] is not None:
        row.variant_schema_json = json.dumps(payload["variant_schema"], ensure_ascii=False)
    if "default_persona" in payload:
        row.default_persona = payload["default_persona"]
    if "default_skill" in payload and payload["default_skill"] is not None:
        row.default_skill_json = json.dumps(payload["default_skill"], ensure_ascii=False)
    if "publish_options" in payload and payload["publish_options"] is not None:
        row.publish_options_json = json.dumps(payload["publish_options"], ensure_ascii=False)
    if "preferred_adapter" in payload:
        row.preferred_adapter = payload["preferred_adapter"]

    db.commit()
    db.refresh(row)
    clear_platform_cache()
    return _custom_row_to_def(row)


def delete_custom_platform(db: Session, platform_id: str) -> None:
    pid = validate_platform_id(platform_id)
    if is_builtin_platform(pid):
        raise PlatformNotCustomError(f"Cannot delete builtin platform: {pid}")

    row = db.query(CustomPlatform).filter(CustomPlatform.id == pid).first()
    if row is None:
        raise ValueError(f"Unknown custom platform: {pid}")

    in_use = db.query(Account).filter(Account.platform == pid).first()
    if in_use is not None:
        raise PlatformInUseError(f"Platform is referenced by account #{in_use.id}")

    db.delete(row)
    db.commit()
    clear_platform_cache()
