from fastapi import APIRouter

from app.schemas.platforms import PlatformResponse, to_platform_response
from app.platforms import list_platforms

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list[PlatformResponse])
def get_platforms() -> list[PlatformResponse]:
    return [to_platform_response(p) for p in list_platforms(enabled_only=True)]
