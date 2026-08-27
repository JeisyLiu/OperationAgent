from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.platforms import list_platforms
from app.schemas.platforms import (
    PlatformCreate,
    PlatformResponse,
    PlatformUpdate,
    to_platform_response,
)
from app.services.platform_service import (
    PlatformConflictError,
    PlatformInUseError,
    PlatformNotCustomError,
    create_custom_platform,
    delete_custom_platform,
    update_custom_platform,
)

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list[PlatformResponse])
def get_platforms(db: Session = Depends(get_db)) -> list[PlatformResponse]:
    return [to_platform_response(p, db=db) for p in list_platforms(enabled_only=True, db=db)]


@router.post("", response_model=PlatformResponse)
def create_platform(payload: PlatformCreate, db: Session = Depends(get_db)) -> PlatformResponse:
    try:
        platform = create_custom_platform(db, payload.model_dump())
    except PlatformConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_platform_response(platform, db=db)


@router.patch("/{platform_id}", response_model=PlatformResponse)
def patch_platform(
    platform_id: str,
    payload: PlatformUpdate,
    db: Session = Depends(get_db),
) -> PlatformResponse:
    try:
        platform = update_custom_platform(
            db,
            platform_id,
            payload.model_dump(exclude_unset=True),
        )
    except PlatformNotCustomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_platform_response(platform, db=db)


@router.delete("/{platform_id}")
def remove_platform(platform_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        delete_custom_platform(db, platform_id)
    except PlatformNotCustomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PlatformInUseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}
