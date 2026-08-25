from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm import llm
from app.schemas.settings import (
    AiSettingsResponse,
    AiSettingsTestResponse,
    AiSettingsUpdate,
)
from app.services.llm_model_service import llm_model_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai", response_model=AiSettingsResponse | None)
def get_ai_settings(db: Session = Depends(get_db)) -> AiSettingsResponse | None:
    primary = llm_model_service.get_primary_config(db)
    if primary is None:
        models = llm_model_service.list_models(db)
        if not models:
            return None
        row = models[0]
        return AiSettingsResponse(
            provider=row.provider,
            base_url=row.base_url,
            model=row.model,
            api_key=row.api_key_masked,
            updated_at=row.updated_at,
        )
    public = llm_model_service.list_models(db)
    match = next((m for m in public if m.id == primary.id), None)
    if match is None:
        return None
    return AiSettingsResponse(
        provider=match.provider,
        base_url=match.base_url,
        model=match.model,
        api_key=match.api_key_masked,
        updated_at=match.updated_at,
    )


@router.put("/ai", response_model=AiSettingsResponse)
def put_ai_settings(
    payload: AiSettingsUpdate,
    db: Session = Depends(get_db),
) -> AiSettingsResponse:
    try:
        dto = llm_model_service.upsert_primary_legacy(
            db,
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AiSettingsResponse(
        provider=dto.provider,
        base_url=dto.base_url,
        model=dto.model,
        api_key=dto.api_key_masked,
        updated_at=dto.updated_at,
    )


@router.post("/ai/test", response_model=AiSettingsTestResponse)
def test_ai_settings(db: Session = Depends(get_db)) -> AiSettingsTestResponse:
    if llm_model_service.get_primary_config(db) is None and not llm_model_service.list_models(db):
        raise HTTPException(status_code=400, detail="AI settings not configured")

    try:
        reply = llm.chat(
            [{"role": "user", "content": "Reply with exactly: pong"}],
            max_tokens=32,
        )
        return AiSettingsTestResponse(ok=True, reply=reply.strip()[:200])
    except Exception as exc:
        return AiSettingsTestResponse(ok=False, error=str(exc))
