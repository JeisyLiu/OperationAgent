from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm import client as llm_client
from app.schemas.settings import (
    AiSettingsResponse,
    AiSettingsTestResponse,
    AiSettingsUpdate,
)
from app.services.settings_service import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai", response_model=AiSettingsResponse | None)
def get_ai_settings(db: Session = Depends(get_db)) -> AiSettingsResponse | None:
    dto = settings_service.get_public(db)
    if dto is None:
        return None
    return AiSettingsResponse(
        provider=dto.provider,
        base_url=dto.base_url,
        model=dto.model,
        api_key=dto.api_key_masked,
        updated_at=dto.updated_at,
    )


@router.put("/ai", response_model=AiSettingsResponse)
def put_ai_settings(
    payload: AiSettingsUpdate,
    db: Session = Depends(get_db),
) -> AiSettingsResponse:
    dto = settings_service.save(
        db,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
    )
    return AiSettingsResponse(
        provider=dto.provider,
        base_url=dto.base_url,
        model=dto.model,
        api_key=dto.api_key_masked,
        updated_at=dto.updated_at,
    )


@router.post("/ai/test", response_model=AiSettingsTestResponse)
def test_ai_settings(db: Session = Depends(get_db)) -> AiSettingsTestResponse:
    secrets = settings_service.get_secrets(db)
    if secrets is None or not secrets.api_key:
        raise HTTPException(status_code=400, detail="AI settings not configured")

    try:
        reply = llm_client.chat(
            [{"role": "user", "content": "Reply with exactly: pong"}],
            secrets,
        )
        summary = reply.strip()[:200]
        return AiSettingsTestResponse(ok=True, reply=summary)
    except Exception as exc:
        return AiSettingsTestResponse(ok=False, error=str(exc))
