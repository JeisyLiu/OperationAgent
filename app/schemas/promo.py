from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.jobs import ExecutionLogResponse


class PromoRunCreate(BaseModel):
    variant_id: int


class PromoCommentResponse(BaseModel):
    id: int
    run_id: int
    target_id: int
    body: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PromoTargetResponse(BaseModel):
    id: int
    run_id: int
    tag: str
    url: str
    title: str | None = None
    description: str | None = None
    status: str
    error_message: str | None = None
    comments: list[PromoCommentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PromoRunResponse(BaseModel):
    id: int
    variant_id: int
    asset_id: int
    account_id: int
    platform: str
    status: str
    tags: list[str] = Field(default_factory=list)
    operation_run_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    targets: list[PromoTargetResponse] = Field(default_factory=list)
    logs: list[ExecutionLogResponse] = Field(default_factory=list)


class PromoRunListResponse(BaseModel):
    items: list[PromoRunResponse]
    total: int


class PromoCommentUpdate(BaseModel):
    body: str
