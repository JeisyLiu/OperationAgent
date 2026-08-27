from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm import llm
from app.llm import pool as llm_pool
from app.schemas.bulk import BulkActionRequest, BulkActionResponse
from app.schemas.llm import (
    LlmModelCreate,
    LlmModelResponse,
    LlmModelTestResponse,
    LlmModelUpdate,
)
from app.services.bulk_actions import bulk_actions_service
from app.services.llm_model_service import llm_model_service

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _to_response(dto) -> LlmModelResponse:
    return LlmModelResponse(
        id=dto.id,
        alias=dto.alias,
        provider=dto.provider,
        base_url=dto.base_url,
        model=dto.model,
        api_key=dto.api_key_masked,
        enabled=dto.enabled,
        priority=dto.priority,
        max_concurrency=dto.max_concurrency,
        timeout_sec=dto.timeout_sec,
        updated_at=dto.updated_at,
    )


@router.get("/models", response_model=list[LlmModelResponse])
def list_llm_models(db: Session = Depends(get_db)) -> list[LlmModelResponse]:
    return [_to_response(row) for row in llm_model_service.list_models(db)]


@router.post("/models", response_model=LlmModelResponse)
def create_llm_model(payload: LlmModelCreate, db: Session = Depends(get_db)) -> LlmModelResponse:
    try:
        row = llm_model_service.create(
            db,
            alias=payload.alias,
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            enabled=payload.enabled,
            priority=payload.priority,
            max_concurrency=payload.max_concurrency,
            timeout_sec=payload.timeout_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/models/bulk", response_model=BulkActionResponse)
def bulk_llm_models(payload: BulkActionRequest, db: Session = Depends(get_db)) -> BulkActionResponse:
    try:
        result = bulk_actions_service.bulk_llm_models(
            db,
            ids=payload.ids,
            action=payload.action,
            on_deleted=llm_pool.invalidate_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.patch("/models/{model_id}", response_model=LlmModelResponse)
def patch_llm_model(
    model_id: int,
    payload: LlmModelUpdate,
    db: Session = Depends(get_db),
) -> LlmModelResponse:
    row = llm_model_service.get(db, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    try:
        updated = llm_model_service.update(
            db,
            row,
            alias=payload.alias,
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            enabled=payload.enabled,
            priority=payload.priority,
            max_concurrency=payload.max_concurrency,
            timeout_sec=payload.timeout_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    llm_pool.invalidate_client(model_id)
    return _to_response(updated)


@router.delete("/models/{model_id}")
def delete_llm_model(model_id: int, db: Session = Depends(get_db)) -> dict:
    row = llm_model_service.get(db, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    llm_model_service.delete(db, row)
    llm_pool.invalidate_client(model_id)
    return {"ok": True}


@router.post("/models/{model_id}/test", response_model=LlmModelTestResponse)
def test_llm_model(model_id: int, db: Session = Depends(get_db)) -> LlmModelTestResponse:
    row = llm_model_service.get(db, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    try:
        reply = llm.chat_single(
            model_id,
            [{"role": "user", "content": "Reply with exactly: pong"}],
            max_tokens=32,
        )
        return LlmModelTestResponse(ok=True, reply=reply.strip()[:200])
    except Exception as exc:
        return LlmModelTestResponse(ok=False, error=str(exc))
