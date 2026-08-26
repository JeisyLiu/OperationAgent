from typing import Any

from pydantic import BaseModel, Field

from app.platforms import has_channel, is_publishable
from app.schemas.accounts import AccountSkill


class PlatformResponse(BaseModel):
    id: str
    display_name: str
    region: str
    enabled: bool
    channel: str | None
    publishable: bool
    has_dedicated_channel: bool
    preferred_adapter: str | None = None
    media_types: list[str]
    default_persona: str | None = None
    default_skill: AccountSkill | None = None
    publish_options: dict[str, Any] = Field(default_factory=dict)


def to_platform_response(platform) -> PlatformResponse:
    default_skill = None
    if platform.default_skill:
        default_skill = AccountSkill.model_validate(platform.default_skill)
    return PlatformResponse(
        id=platform.id,
        display_name=platform.display_name,
        region=platform.region,
        enabled=platform.enabled,
        channel=platform.channel,
        publishable=is_publishable(platform.id),
        has_dedicated_channel=has_channel(platform.channel) if platform.channel else False,
        preferred_adapter=platform.preferred_adapter,
        media_types=platform.media_types,
        default_persona=platform.default_persona,
        default_skill=default_skill,
        publish_options=dict(platform.publish_options or {}),
    )
