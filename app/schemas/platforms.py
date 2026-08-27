from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.platforms import has_channel, is_publishable
from app.platforms.loader import PLATFORM_ID_RE
from app.schemas.accounts import AccountSkill


class PlatformResponse(BaseModel):
    id: str
    display_name: str
    region: str
    enabled: bool
    channel: str | None
    source: Literal["builtin", "custom"] = "builtin"
    publishable: bool
    has_dedicated_channel: bool
    preferred_adapter: str | None = None
    media_types: list[str]
    home_url: str | None = None
    login_url: str | None = None
    upload_url: str | None = None
    default_persona: str | None = None
    default_skill: AccountSkill | None = None
    publish_options: dict[str, Any] = Field(default_factory=dict)


class PlatformCreate(BaseModel):
    id: str
    display_name: str
    region: str = "global"
    home_url: str
    login_url: str | None = None
    upload_url: str | None = None
    enabled: bool = True
    media_types: list[str] = Field(default_factory=lambda: ["text"])
    variant_schema: dict[str, Any] = Field(default_factory=dict)
    default_persona: str | None = None
    default_skill: dict[str, Any] = Field(default_factory=dict)
    publish_options: dict[str, Any] = Field(default_factory=dict)
    preferred_adapter: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        pid = value.strip().lower()
        if not PLATFORM_ID_RE.match(pid):
            raise ValueError("id must match ^[a-z][a-z0-9_]{1,31}$")
        return pid


class PlatformUpdate(BaseModel):
    display_name: str | None = None
    region: str | None = None
    home_url: str | None = None
    login_url: str | None = None
    upload_url: str | None = None
    enabled: bool | None = None
    media_types: list[str] | None = None
    variant_schema: dict[str, Any] | None = None
    default_persona: str | None = None
    default_skill: dict[str, Any] | None = None
    publish_options: dict[str, Any] | None = None
    preferred_adapter: str | None = None


def to_platform_response(platform, *, db=None) -> PlatformResponse:
    default_skill = None
    if platform.default_skill:
        default_skill = AccountSkill.model_validate(platform.default_skill)
    return PlatformResponse(
        id=platform.id,
        display_name=platform.display_name,
        region=platform.region,
        enabled=platform.enabled,
        channel=platform.channel,
        source=getattr(platform, "source", "builtin"),
        publishable=is_publishable(platform.id, db=db),
        has_dedicated_channel=has_channel(platform.id, db=db) if platform.channel else False,
        preferred_adapter=platform.preferred_adapter,
        media_types=platform.media_types,
        home_url=platform.home_url,
        login_url=platform.login_url,
        upload_url=platform.upload_url,
        default_persona=platform.default_persona,
        default_skill=default_skill,
        publish_options=dict(platform.publish_options or {}),
    )
