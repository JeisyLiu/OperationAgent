from datetime import datetime

from pydantic import BaseModel, Field


class AssetCreate(BaseModel):
    title: str
    media_type: str = "video"
    base_caption: str | None = None
    language: str | None = None
    category: str | None = None


class AssetResponse(BaseModel):
    id: int
    title: str
    media_type: str
    file_path: str | None = None
    base_caption: str | None = None
    language: str | None = None
    category: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VariantCreate(BaseModel):
    asset_id: int
    platform: str = "tiktok"
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    media_path: str | None = None


class VariantUpdate(BaseModel):
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    status: str | None = None


class VariantResponse(BaseModel):
    id: int
    asset_id: int
    platform: str
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    media_path: str | None = None
    status: str

    model_config = {"from_attributes": True}
