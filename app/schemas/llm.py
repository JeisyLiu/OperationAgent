from datetime import datetime

from pydantic import BaseModel, Field


class LlmModelResponse(BaseModel):
    id: int
    alias: str
    provider: str
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(None, description="Masked API key")
    enabled: bool = True
    priority: int = 0
    max_concurrency: int = 4
    timeout_sec: int = 60
    updated_at: datetime | None = None


class LlmModelCreate(BaseModel):
    alias: str
    provider: str = "openai"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    enabled: bool = True
    priority: int = 0
    max_concurrency: int = 4
    timeout_sec: int = 60


class LlmModelUpdate(BaseModel):
    alias: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    max_concurrency: int | None = None
    timeout_sec: int | None = None


class LlmModelTestResponse(BaseModel):
    ok: bool
    reply: str | None = None
    error: str | None = None
