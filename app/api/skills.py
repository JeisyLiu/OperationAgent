from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.accounts import AccountSkill
from app.schemas.skills import (
    SkillOverlayResponse,
    SkillOverlayUpdate,
    SkillRoleAdminResponse,
    SkillRoleDetail,
    SkillRolePreview,
    SkillRoleSummary,
    SkillRoleUpdate,
    SkillTagResponse,
)
from app.skills.loader import get_overlay, get_role, list_roles, list_tags, preview_resolved

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/roles", response_model=list[SkillRoleSummary])
def list_skill_roles(db: Session = Depends(get_db)) -> list[SkillRoleSummary]:
    return [
        SkillRoleSummary(id=role.id, display_name=role.display_name, description=role.description)
        for role in list_roles(db)
    ]


@router.get("/tags", response_model=list[SkillTagResponse])
def list_skill_tags() -> list[SkillTagResponse]:
    return [SkillTagResponse(id=tag.id, display_name=tag.display_name) for tag in list_tags()]


@router.get("/roles/{role_id}", response_model=SkillRoleDetail)
def get_skill_role(role_id: str, db: Session = Depends(get_db)) -> SkillRoleDetail:
    role = get_role(role_id, db)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return SkillRoleDetail(
        id=role.id,
        display_name=role.display_name,
        description=role.description,
        default_persona=role.default_persona,
        skill=AccountSkill.model_validate(role.skill),
    )


@router.get("/roles/{role_id}/preview", response_model=SkillRolePreview)
def preview_skill_role(
    role_id: str,
    platform: str = Query(..., min_length=1),
    role_tags: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
) -> SkillRolePreview:
    if get_role(role_id, db) is None:
        raise HTTPException(status_code=404, detail="Role not found")
    data = preview_resolved(platform=platform, role_id=role_id, role_tags=role_tags, db=db)
    return SkillRolePreview(
        role_id=role_id,
        role_tags=role_tags,
        role_display_name=data.get("role_display_name"),
        persona=data["persona"],
        skill=AccountSkill.model_validate(data["skill"]) if data.get("skill") else None,
    )


@router.put("/roles/{role_id}", response_model=SkillRoleAdminResponse)
def update_skill_role(
    role_id: str,
    payload: SkillRoleUpdate,
    db: Session = Depends(get_db),
) -> SkillRoleAdminResponse:
    from datetime import datetime

    from app.db.models import SkillRole as SkillRoleRow

    row = db.query(SkillRoleRow).filter(SkillRoleRow.id == role_id).first()
    if row is None:
        role = get_role(role_id, db)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        row = SkillRoleRow(
            id=role.id,
            display_name=role.display_name,
            description=role.description,
            persona=role.default_persona,
            skill_json=__import__("json").dumps(role.skill, ensure_ascii=False),
        )
        db.add(row)
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.description is not None:
        row.description = payload.description
    if payload.default_persona is not None:
        row.persona = payload.default_persona
    if payload.skill is not None:
        row.skill_json = payload.skill.model_dump_json(exclude_none=True)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return SkillRoleAdminResponse(
        id=row.id,
        display_name=row.display_name,
        description=row.description or "",
        default_persona=row.persona or "",
        skill=AccountSkill.model_validate(__import__("json").loads(row.skill_json or "{}")),
        updated_at=row.updated_at,
        source="db",
    )


@router.get("/roles/{role_id}/overlays/{platform}", response_model=SkillOverlayResponse)
def get_skill_overlay(
    role_id: str,
    platform: str,
    db: Session = Depends(get_db),
) -> SkillOverlayResponse:
    if get_role(role_id, db) is None:
        raise HTTPException(status_code=404, detail="Role not found")

    from app.db.models import SkillRoleOverlay

    db_row = (
        db.query(SkillRoleOverlay)
        .filter(SkillRoleOverlay.role_id == role_id, SkillRoleOverlay.platform == platform)
        .first()
    )
    if db_row is not None:
        try:
            skill_data = __import__("json").loads(db_row.skill_json or "{}")
        except Exception:
            skill_data = {}
        return SkillOverlayResponse(
            role_id=role_id,
            platform=platform,
            skill=AccountSkill.model_validate(skill_data),
            persona_suffix=db_row.persona_suffix,
            source="db",
            exists=True,
        )

    overlay = get_overlay(role_id, platform, exact=True)
    if overlay is not None:
        return SkillOverlayResponse(
            role_id=role_id,
            platform=platform,
            skill=AccountSkill.model_validate(overlay.skill),
            persona_suffix=overlay.persona_suffix,
            source="file",
            exists=True,
        )

    return SkillOverlayResponse(
        role_id=role_id,
        platform=platform,
        skill=AccountSkill(),
        persona_suffix=None,
        source="empty",
        exists=False,
    )


@router.put("/roles/{role_id}/overlays/{platform}", response_model=SkillRolePreview)
def update_skill_overlay(
    role_id: str,
    platform: str,
    payload: SkillOverlayUpdate,
    db: Session = Depends(get_db),
) -> SkillRolePreview:
    from datetime import datetime

    from app.db.models import SkillRoleOverlay

    if get_role(role_id, db) is None:
        raise HTTPException(status_code=404, detail="Role not found")
    row = (
        db.query(SkillRoleOverlay)
        .filter(SkillRoleOverlay.role_id == role_id, SkillRoleOverlay.platform == platform)
        .first()
    )
    if row is None:
        row = SkillRoleOverlay(role_id=role_id, platform=platform)
        db.add(row)
    if payload.skill is not None:
        row.skill_json = payload.skill.model_dump_json(exclude_none=True)
    if payload.persona_suffix is not None:
        row.persona_suffix = payload.persona_suffix
    row.updated_at = datetime.utcnow()
    db.commit()
    preview_platform = platform if platform != "_default" else "tiktok"
    data = preview_resolved(platform=preview_platform, role_id=role_id, db=db)
    return SkillRolePreview(
        role_id=role_id,
        role_display_name=data.get("role_display_name"),
        persona=data["persona"],
        skill=AccountSkill.model_validate(data["skill"]) if data.get("skill") else None,
    )
