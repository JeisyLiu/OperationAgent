from datetime import datetime

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    content_variant_id: int
    account_id: int
    scheduled_at: datetime | None = None
    max_retries: int = 3


class BulkJobItem(BaseModel):
    content_variant_id: int
    account_id: int
    scheduled_at: datetime | None = None
    max_retries: int = 3


class BulkJobCreate(BaseModel):
    items: list[BulkJobItem]


class BulkJobResultItem(BaseModel):
    content_variant_id: int
    account_id: int
    detail: str


class JobResponse(BaseModel):
    id: int
    content_variant_id: int
    account_id: int
    platform: str
    browser_profile: str
    scheduled_at: datetime
    status: str
    retry_count: int
    max_retries: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class BulkJobResponse(BaseModel):
    created: list[JobResponse]
    failed: list[BulkJobResultItem] = Field(default_factory=list)


class ExecutionLogResponse(BaseModel):
    id: int
    job_id: int
    step: str
    message: str | None = None
    screenshot_path: str | None = None
    tool_name: str | None = None
    status: str | None = None
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    payload_json: str | None = None
    started_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobDetailTotals(BaseModel):
    duration_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class JobDetailResponse(BaseModel):
    job: JobResponse
    steps: list[ExecutionLogResponse]
    totals: JobDetailTotals
    account_id: int
