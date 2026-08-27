from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.accounts import AccountSkill

SKILLS_DIR = Path(__file__).resolve().parent
ROLES_DIR = SKILLS_DIR / "roles"
OVERLAYS_DIR = SKILLS_DIR / "overlays"
TAGS_FILE = SKILLS_DIR / "tags.json"

PLATFORMS_WITH_OVERLAY = ("rednote", "douyin", "tiktok", "weibo", "twitter", "bilibili")


@dataclass(frozen=True)
class SkillRole:
    id: str
    display_name: str
    description: str
    default_persona: str
    skill: dict[str, Any]


@dataclass(frozen=True)
class SkillOverlay:
    platform: str
    skill: dict[str, Any]
    persona_suffix: str | None = None


@dataclass(frozen=True)
class SkillTag:
    id: str
    display_name: str
    skill: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _role_from_dict(data: dict[str, Any]) -> SkillRole:
    return SkillRole(
        id=data["id"],
        display_name=data["display_name"],
        description=data.get("description", ""),
        default_persona=data.get("default_persona", ""),
        skill=dict(data.get("skill") or {}),
    )


def _overlay_from_dict(platform: str, data: dict[str, Any]) -> SkillOverlay:
    return SkillOverlay(
        platform=platform,
        skill=dict(data.get("skill") or {}),
        persona_suffix=data.get("persona_suffix"),
    )


def _load_role_from_file(role_id: str) -> SkillRole | None:
    path = ROLES_DIR / f"{role_id}.json"
    if not path.is_file():
        return None
    data = _read_json(path)
    if data.get("id") != role_id:
        data = {**data, "id": role_id}
    return _role_from_dict(data)


def _load_overlay_from_file(role_id: str, platform: str, *, exact: bool = False) -> SkillOverlay | None:
    role_dir = OVERLAYS_DIR / role_id
    if not role_dir.is_dir():
        return None
    names = (f"{platform}.json",) if exact else (f"{platform}.json", "_default.json")
    for name in names:
        path = role_dir / name
        if path.is_file():
            return _overlay_from_dict(platform, _read_json(path))
    return None


def _load_role_from_db(db: Session, role_id: str) -> SkillRole | None:
    from app.db.models import SkillRole as SkillRoleRow

    row = db.query(SkillRoleRow).filter(SkillRoleRow.id == role_id).first()
    if row is None:
        return None
    try:
        skill = json.loads(row.skill_json or "{}")
    except json.JSONDecodeError:
        skill = {}
    return SkillRole(
        id=row.id,
        display_name=row.display_name,
        description=row.description or "",
        default_persona=row.persona or "",
        skill=skill,
    )


def _load_overlay_from_db(
    db: Session, role_id: str, platform: str, *, exact: bool = False
) -> SkillOverlay | None:
    from app.db.models import SkillRoleOverlay

    row = (
        db.query(SkillRoleOverlay)
        .filter(SkillRoleOverlay.role_id == role_id, SkillRoleOverlay.platform == platform)
        .first()
    )
    if row is None and not exact:
        row = (
            db.query(SkillRoleOverlay)
            .filter(SkillRoleOverlay.role_id == role_id, SkillRoleOverlay.platform == "_default")
            .first()
        )
    if row is None:
        return None
    try:
        skill = json.loads(row.skill_json or "{}")
    except json.JSONDecodeError:
        skill = {}
    return SkillOverlay(
        platform=platform,
        skill=skill,
        persona_suffix=row.persona_suffix,
    )


def get_role(role_id: str, db: Session | None = None) -> SkillRole | None:
    if not role_id:
        return None
    if db is not None:
        role = _load_role_from_db(db, role_id)
        if role is not None:
            return role
    return _load_role_from_file(role_id)


def get_overlay(
    role_id: str,
    platform: str,
    db: Session | None = None,
    *,
    exact: bool = False,
) -> SkillOverlay | None:
    if not role_id:
        return None
    if db is not None:
        overlay = _load_overlay_from_db(db, role_id, platform, exact=exact)
        if overlay is not None:
            return overlay
    return _load_overlay_from_file(role_id, platform, exact=exact)


@lru_cache(maxsize=1)
def list_roles_from_files() -> list[SkillRole]:
    if not ROLES_DIR.is_dir():
        return []
    roles: list[SkillRole] = []
    for path in sorted(ROLES_DIR.glob("*.json")):
        role = _load_role_from_file(path.stem)
        if role is not None:
            roles.append(role)
    return roles


def list_roles(db: Session | None = None) -> list[SkillRole]:
    if db is not None:
        from app.db.models import SkillRole as SkillRoleRow

        rows = db.query(SkillRoleRow).order_by(SkillRoleRow.id.asc()).all()
        if rows:
            result: list[SkillRole] = []
            for row in rows:
                role = _load_role_from_db(db, row.id)
                if role is not None:
                    result.append(role)
            return result
    return list_roles_from_files()


@lru_cache(maxsize=1)
def _tags_from_file() -> dict[str, SkillTag]:
    if not TAGS_FILE.is_file():
        return {}
    data = _read_json(TAGS_FILE)
    tags: dict[str, SkillTag] = {}
    for item in data.get("tags", []):
        tag_id = item["id"]
        tags[tag_id] = SkillTag(
            id=tag_id,
            display_name=item.get("display_name", tag_id),
            skill=dict(item.get("skill") or {}),
        )
    return tags


def list_tags() -> list[SkillTag]:
    return list(_tags_from_file().values())


def merge_tag_skills(tag_ids: list[str] | None) -> AccountSkill | None:
    if not tag_ids:
        return None
    catalog = _tags_from_file()
    merged: AccountSkill | None = None
    for tag_id in tag_ids:
        tag = catalog.get(tag_id)
        if tag is None:
            continue
        layer = AccountSkill.model_validate(tag.skill)
        merged = layer if merged is None else _merge_skills(merged, layer)
    return merged


def _skill_from_dict(data: dict[str, Any] | None) -> AccountSkill | None:
    if not data:
        return None
    return AccountSkill.model_validate(data)


def _merge_skills(base: AccountSkill, override: AccountSkill | None) -> AccountSkill:
    if override is None:
        return base
    return AccountSkill(
        tone=override.tone or base.tone,
        audience=override.audience or base.audience,
        language=override.language or base.language,
        taboos=override.taboos if override.taboos else base.taboos,
        cta=override.cta or base.cta,
        topics=override.topics if override.topics else base.topics,
        hashtag_style=override.hashtag_style or base.hashtag_style,
        extra_prompt=override.extra_prompt or base.extra_prompt,
        content_goals=override.content_goals if override.content_goals else base.content_goals,
        claim_policy=override.claim_policy or base.claim_policy,
        structure=override.structure if override.structure else base.structure,
        evidence_style=override.evidence_style or base.evidence_style,
        disclaimer=override.disclaimer or base.disclaimer,
        interaction_style=override.interaction_style or base.interaction_style,
    )


def merge_skill_layers(*layers: AccountSkill | None) -> AccountSkill | None:
    result: AccountSkill | None = None
    for layer in layers:
        if layer is None:
            continue
        result = layer if result is None else _merge_skills(result, layer)
    return result


def preview_resolved(
    *,
    platform: str,
    role_id: str | None = None,
    role_tags: list[str] | None = None,
    account_skill: AccountSkill | None = None,
    account_persona: str | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    from app.platforms import get_platform_default_persona, get_platform_default_skill

    platform_skill = _skill_from_dict(get_platform_default_skill(platform))
    role = get_role(role_id, db) if role_id else None
    role_skill = _skill_from_dict(role.skill) if role else None
    overlay = get_overlay(role_id, platform, db) if role_id else None
    overlay_skill = _skill_from_dict(overlay.skill) if overlay else None
    tag_skill = merge_tag_skills(role_tags)
    resolved_skill = merge_skill_layers(platform_skill, role_skill, overlay_skill, tag_skill, account_skill)

    persona = account_persona
    if not persona:
        persona = get_platform_default_persona(platform) or ""
        if role and role.default_persona:
            persona = role.default_persona
        if overlay and overlay.persona_suffix:
            persona = f"{persona}{overlay.persona_suffix}"

    return {
        "role_id": role_id,
        "role_tags": role_tags or [],
        "persona": persona,
        "skill": resolved_skill.model_dump(exclude_none=True) if resolved_skill else None,
        "role_display_name": role.display_name if role else None,
    }
