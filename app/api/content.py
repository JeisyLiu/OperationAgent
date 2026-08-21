import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import ContentVariant
from app.db.session import get_db
from app.schemas.content import (
    AssetCreate,
    AssetResponse,
    VariantCreate,
    VariantResponse,
    VariantUpdate,
)
from app.services.content_service import content_service

router = APIRouter(prefix="/api/content", tags=["content"])


def _variant_response(variant: ContentVariant) -> VariantResponse:
    hashtags = json.loads(variant.hashtags_json or "[]")
    return VariantResponse(
        id=variant.id,
        asset_id=variant.asset_id,
        platform=variant.platform,
        title=variant.title,
        caption=variant.caption,
        hashtags=hashtags,
        media_path=variant.media_path,
        status=variant.status,
    )


@router.get("/assets", response_model=list[AssetResponse])
def list_assets(db: Session = Depends(get_db)) -> list[AssetResponse]:
    return content_service.list_assets(db)


@router.post("/assets", response_model=AssetResponse)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetResponse:
    return content_service.create_asset(
        db,
        title=payload.title,
        media_type=payload.media_type,
        base_caption=payload.base_caption,
        language=payload.language,
        category=payload.category,
    )


@router.post("/assets/{asset_id}/upload", response_model=AssetResponse)
async def upload_asset(
    asset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AssetResponse:
    asset = content_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    data = await file.read()
    return content_service.save_upload(db, asset, file.filename or "upload.bin", data)


@router.get("/variants", response_model=list[VariantResponse])
def list_variants(asset_id: int | None = None, db: Session = Depends(get_db)) -> list[VariantResponse]:
    variants = content_service.list_variants(db, asset_id=asset_id)
    return [_variant_response(v) for v in variants]


@router.post("/variants", response_model=VariantResponse)
def create_variant(payload: VariantCreate, db: Session = Depends(get_db)) -> VariantResponse:
    try:
        variant = content_service.create_variant(
            db,
            asset_id=payload.asset_id,
            platform=payload.platform,
            title=payload.title,
            caption=payload.caption,
            hashtags=payload.hashtags,
            media_path=payload.media_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _variant_response(variant)


@router.get("/variants/{variant_id}", response_model=VariantResponse)
def get_variant(variant_id: int, db: Session = Depends(get_db)) -> VariantResponse:
    variant = content_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return _variant_response(variant)


@router.patch("/variants/{variant_id}", response_model=VariantResponse)
def patch_variant(
    variant_id: int,
    payload: VariantUpdate,
    db: Session = Depends(get_db),
) -> VariantResponse:
    variant = content_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    updated = content_service.update_variant(
        db,
        variant,
        title=payload.title,
        caption=payload.caption,
        hashtags=payload.hashtags,
        status=payload.status,
    )
    return _variant_response(updated)
