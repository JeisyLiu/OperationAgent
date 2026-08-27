import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.jobs import ExecutionLogResponse


class HistoryItemResponse(BaseModel):
    id: str
    source: Literal["operation", "job"]
    kind: str
    title: str
    status: str
    total_tokens: int | None = None
    created_at: datetime
    ref_id: int


class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    limit: int
    offset: int


class OperationStepResponse(BaseModel):
    id: int
    run_id: int
    account_id: int | None = None
    platform: str | None = None
    variant_id: int | None = None
    status: str
    attempt: int
    model_id: int | None = None
    model_alias: str | None = None
    skill: dict[str, Any] = Field(default_factory=dict)
    persona: str | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    response_text: str | None = None
    parsed: dict[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OperationRunResponse(BaseModel):
    id: int
    kind: str
    status: str
    asset_id: int | None = None
    account_ids: list[int] = Field(default_factory=list)
    variant_ids: list[int] = Field(default_factory=list)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    steps: list[OperationStepResponse] = Field(default_factory=list)
    execution_logs: list[ExecutionLogResponse] = Field(default_factory=list)
    promo_run_id: int | None = None


def operation_step_to_response(step) -> OperationStepResponse:
    skill = {}
    if step.skill_json:
        try:
            skill = json.loads(step.skill_json)
        except json.JSONDecodeError:
            skill = {}
    messages = []
    if step.messages_json:
        try:
            messages = json.loads(step.messages_json)
        except json.JSONDecodeError:
            messages = []
    parsed = None
    if step.parsed_json:
        try:
            parsed = json.loads(step.parsed_json)
        except json.JSONDecodeError:
            parsed = None
    return OperationStepResponse(
        id=step.id,
        run_id=step.run_id,
        account_id=step.account_id,
        platform=step.platform,
        variant_id=step.variant_id,
        status=step.status,
        attempt=step.attempt,
        model_id=step.model_id,
        model_alias=step.model_alias,
        skill=skill,
        persona=step.persona,
        messages=messages,
        response_text=step.response_text,
        parsed=parsed,
        prompt_tokens=step.prompt_tokens,
        completion_tokens=step.completion_tokens,
        total_tokens=step.total_tokens,
        duration_ms=step.duration_ms,
        error_message=step.error_message,
        created_at=step.created_at,
    )


def operation_run_to_response(
    run,
    steps: list,
    *,
    execution_logs: list | None = None,
    promo_run_id: int | None = None,
) -> OperationRunResponse:
    account_ids = []
    if run.account_ids_json:
        try:
            account_ids = json.loads(run.account_ids_json)
        except json.JSONDecodeError:
            account_ids = []
    variant_ids = []
    if run.variant_ids_json:
        try:
            variant_ids = json.loads(run.variant_ids_json)
        except json.JSONDecodeError:
            variant_ids = []
    input_snapshot = {}
    if run.input_json:
        try:
            input_snapshot = json.loads(run.input_json)
        except json.JSONDecodeError:
            input_snapshot = {}
    if promo_run_id is None:
        raw_promo = input_snapshot.get("promo_run_id")
        try:
            promo_run_id = int(raw_promo) if raw_promo is not None else None
        except (TypeError, ValueError):
            promo_run_id = None
    return OperationRunResponse(
        id=run.id,
        kind=run.kind,
        status=run.status,
        asset_id=run.asset_id,
        account_ids=account_ids,
        variant_ids=variant_ids,
        input_snapshot=input_snapshot,
        summary=run.summary,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        total_tokens=run.total_tokens,
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
        steps=[operation_step_to_response(s) for s in steps],
        execution_logs=[
            ExecutionLogResponse.model_validate(log) for log in (execution_logs or [])
        ],
        promo_run_id=promo_run_id,
    )
