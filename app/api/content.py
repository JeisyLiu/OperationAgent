import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import ContentVariant
from app.db.session import get_db
from app.schemas.bulk import BulkActionRequest, BulkActionResponse
from app.schemas.content import (
    AssetCreate,
    AssetResponse,
    GenerateVariantsRequest,
    GenerateVariantsResponse,
    GenerateVariantErrorItem,
    VariantCreate,
    VariantListResponse,
    VariantResponse,
    VariantUpdate,
)
from app.services.bulk_actions import bulk_actions_service
from app.services.event_bus import emit_job_updated, emit_readiness_changed
from app.services.content_generate_service import content_generate_service
from app.services.content_service import content_service

router = APIRouter(prefix="/api/content", tags=["content"])


def _variant_response(variant: ContentVariant) -> VariantResponse:
    hashtags = json.loads(variant.hashtags_json or "[]")
    extra = json.loads(variant.extra_json or "{}")
    return VariantResponse(
        id=variant.id,
        asset_id=variant.asset_id,
        platform=variant.platform,
        title=variant.title,
        caption=variant.caption,
        hashtags=hashtags,
        media_path=variant.media_path,
        section=extra.get("section"),
        status=variant.status,
        account_id=extra.get("account_id"),
        account_name=extra.get("account_name"),
        generated_by=extra.get("generated_by"),
    )


def _asset_response(asset) -> AssetResponse:
    return AssetResponse(**content_service.asset_to_dict(asset))


@router.get("/assets", response_model=list[AssetResponse])
def list_assets(db: Session = Depends(get_db)) -> list[AssetResponse]:
    return [_asset_response(a) for a in content_service.list_assets(db)]


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: int, db: Session = Depends(get_db)) -> AssetResponse:
    asset = content_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _asset_response(asset)


@router.post("/assets", response_model=AssetResponse)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetResponse:
    asset = content_service.create_asset(
        db,
        title=payload.title,
        base_caption=payload.base_caption,
        media_type=payload.media_type,
        language=payload.language,
        category=payload.category,
        tags=payload.tags,
    )
    return _asset_response(asset)


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
    asset = content_service.save_upload(db, asset, file.filename or "upload.bin", data)
    return _asset_response(asset)


@router.post("/assets/{asset_id}/upload-images", response_model=AssetResponse)
async def upload_images(
    asset_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> AssetResponse:
    asset = content_service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not files:
        raise HTTPException(status_code=400, detail="No images provided")
    payloads = []
    for upload in files:
        data = await upload.read()
        payloads.append((upload.filename or "image.jpg", data))
    asset = content_service.save_images(db, asset, payloads)
    return _asset_response(asset)


@router.post("/assets/{asset_id}/generate-variants", response_model=GenerateVariantsResponse)
def generate_variants(
    asset_id: int,
    payload: GenerateVariantsRequest,
    db: Session = Depends(get_db),
) -> GenerateVariantsResponse:
    try:
        result = content_generate_service.generate_for_accounts(
            db,
            asset_id=asset_id,
            account_ids=payload.account_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenerateVariantsResponse(
        variants=[_variant_response(v) for v in result.variants],
        errors=[
            GenerateVariantErrorItem(account_id=e.account_id, detail=e.detail) for e in result.errors
        ],
    )


@router.get("/variants", response_model=VariantListResponse)
def list_variants(
    id: int | None = None,
    asset_id: int | None = None,
    platform: str | None = None,
    status: str | None = None,
    account_id: int | None = None,
    q: str | None = None,
    generated_by: str | None = None,
    sort: str = "id",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> VariantListResponse:
    items, total = content_service.search_variants(
        db,
        variant_id=id,
        asset_id=asset_id,
        platform=platform,
        status=status,
        account_id=account_id,
        q=q,
        generated_by=generated_by,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    return VariantListResponse(
        items=[_variant_response(v) for v in items],
        total=total,
        page=max(1, page),
        page_size=min(max(1, page_size), 100),
    )


@router.post("/variants", response_model=VariantResponse)
def create_variant(payload: VariantCreate, db: Session = Depends(get_db)) -> VariantResponse:
    extra = {}
    if payload.section:
        extra["section"] = payload.section
    try:
        variant = content_service.create_variant(
            db,
            asset_id=payload.asset_id,
            platform=payload.platform,
            title=payload.title,
            caption=payload.caption,
            hashtags=payload.hashtags,
            media_path=payload.media_path,
            extra=extra or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _variant_response(variant)


@router.post("/variants/bulk", response_model=BulkActionResponse)
def bulk_variants(payload: BulkActionRequest, db: Session = Depends(get_db)) -> BulkActionResponse:
    enqueued_jobs: list = []

    def on_enqueued(job) -> None:
        enqueued_jobs.append(job)

    try:
        result = bulk_actions_service.bulk_variants(
            db,
            ids=payload.ids,
            action=payload.action,
            on_enqueued=on_enqueued,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.action == "enqueue":
        for job in enqueued_jobs:
            emit_job_updated(job.id, job.status)
        if enqueued_jobs:
            emit_readiness_changed()
    return result


@router.get("/variants/{variant_id}", response_model=VariantResponse)
def get_variant(variant_id: int, db: Session = Depends(get_db)) -> VariantResponse:
    variant = content_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return _variant_response(variant)


@router.post("/variants/{variant_id}/rewrite", response_model=VariantResponse)
def rewrite_variant(variant_id: int, db: Session = Depends(get_db)) -> VariantResponse:
    try:
        variant = content_generate_service.rewrite_variant(db, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        section=payload.section,
        status=payload.status,
    )
    return _variant_response(updated)


@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: int, db: Session = Depends(get_db)) -> dict:
    variant = content_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    try:
        content_service.delete_variant(db, variant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
