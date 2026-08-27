from datetime import datetime

from pydantic import BaseModel, Field


class AccountSkill(BaseModel):
    tone: str | None = None
    audience: str | None = None
    language: str | None = None
    taboos: list[str] = Field(default_factory=list)
    cta: str | None = None
    topics: list[str] = Field(default_factory=list)
    hashtag_style: str | None = None
    extra_prompt: str | None = None
    content_goals: list[str] = Field(default_factory=list)
    claim_policy: str | None = None
    structure: list[str] = Field(default_factory=list)
    evidence_style: str | None = None
    disclaimer: str | None = None
    interaction_style: str | None = None


class AccountCreate(BaseModel):
    platform: str
    account_name: str
    persona: str | None = None
    language: str | None = None
    description: str | None = None
    role_id: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    skill: AccountSkill | None = None


class AccountUpdate(BaseModel):
    account_name: str | None = None
    persona: str | None = None
    language: str | None = None
    description: str | None = None
    status: str | None = None
    role_id: str | None = None
    role_tags: list[str] | None = None
    skill: AccountSkill | None = None
    clear_skill_override: bool = False


class AccountResponse(BaseModel):
    id: int
    platform: str
    account_name: str
    browser_profile: str
    persona: str | None = None
    language: str | None = None
    description: str | None = None
    role_id: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    role_display_name: str | None = None
    skill: AccountSkill | None = None
    template_skill: AccountSkill | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountActionResponse(BaseModel):
    status: str
    message: str


class SessionCheckResponse(BaseModel):
    logged_in: bool
    account_status: str
    message: str
