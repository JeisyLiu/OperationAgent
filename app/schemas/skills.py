from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.accounts import AccountSkill


class SkillRoleSummary(BaseModel):
    id: str
    display_name: str
    description: str


class SkillRoleDetail(BaseModel):
    id: str
    display_name: str
    description: str
    default_persona: str
    skill: AccountSkill


class SkillRolePreview(BaseModel):
    role_id: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    role_display_name: str | None = None
    persona: str
    skill: AccountSkill | None = None


class SkillTagResponse(BaseModel):
    id: str
    display_name: str


class SkillRoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    default_persona: str | None = None
    skill: AccountSkill | None = None


class SkillOverlayUpdate(BaseModel):
    skill: AccountSkill | None = None
    persona_suffix: str | None = None


class SkillOverlayResponse(BaseModel):
    role_id: str
    platform: str
    skill: AccountSkill = Field(default_factory=AccountSkill)
    persona_suffix: str | None = None
    source: str = "empty"
    exists: bool = False


class SkillRoleAdminResponse(BaseModel):
    id: str
    display_name: str
    description: str
    default_persona: str
    skill: AccountSkill
    updated_at: datetime | None = None
    source: str = "file"
