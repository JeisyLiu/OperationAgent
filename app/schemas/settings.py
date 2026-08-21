from datetime import datetime

from pydantic import BaseModel, Field


class AiSettingsResponse(BaseModel):
    provider: str
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(None, description="Masked API key")
    updated_at: datetime | None = None


class AiSettingsUpdate(BaseModel):
    provider: str = "openai"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class AiSettingsTestResponse(BaseModel):
    ok: bool
    reply: str | None = None
    error: str | None = None
