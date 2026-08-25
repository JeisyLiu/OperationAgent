from pydantic import BaseModel

from app.platforms import is_publishable, list_platforms


class PlatformResponse(BaseModel):
    id: str
    display_name: str
    region: str
    enabled: bool
    channel: str | None
    publishable: bool
    media_types: list[str]


def to_platform_response(platform) -> PlatformResponse:
    return PlatformResponse(
        id=platform.id,
        display_name=platform.display_name,
        region=platform.region,
        enabled=platform.enabled,
        channel=platform.channel,
        publishable=is_publishable(platform.id),
        media_types=platform.media_types,
    )
