from datetime import datetime

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    platform: str
    account_name: str
    persona: str | None = None
    language: str | None = None
    description: str | None = None


class AccountUpdate(BaseModel):
    account_name: str | None = None
    persona: str | None = None
    language: str | None = None
    description: str | None = None
    status: str | None = None


class AccountResponse(BaseModel):
    id: int
    platform: str
    account_name: str
    browser_profile: str
    persona: str | None = None
    language: str | None = None
    description: str | None = None
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
