import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import SkillRole, SkillRoleOverlay
from app.skills.loader import OVERLAYS_DIR, list_roles_from_files


def seed_skill_templates(db: Session) -> int:
    """Insert missing file-based role/overlay templates.

    Existing primary keys are never overwritten, so user edits in DB are kept.
    New JSON files are still imported on later startups.
    """
    imported = 0
    now = datetime.utcnow()

    for role in list_roles_from_files():
        existing_role = db.query(SkillRole).filter(SkillRole.id == role.id).first()
        if existing_role is None:
            db.add(
                SkillRole(
                    id=role.id,
                    display_name=role.display_name,
                    description=role.description,
                    persona=role.default_persona,
                    skill_json=json.dumps(role.skill, ensure_ascii=False),
                    updated_at=now,
                )
            )
            imported += 1

        overlay_dir = OVERLAYS_DIR / role.id
        if not overlay_dir.is_dir():
            continue
        for path in sorted(overlay_dir.glob("*.json")):
            platform = path.stem
            exists = (
                db.query(SkillRoleOverlay)
                .filter(
                    SkillRoleOverlay.role_id == role.id,
                    SkillRoleOverlay.platform == platform,
                )
                .first()
            )
            if exists is not None:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            db.add(
                SkillRoleOverlay(
                    role_id=role.id,
                    platform=platform,
                    skill_json=json.dumps(data.get("skill") or {}, ensure_ascii=False),
                    persona_suffix=data.get("persona_suffix"),
                    updated_at=now,
                )
            )
            imported += 1

    if imported:
        db.commit()
    return imported
