from datetime import datetime

from pydantic import BaseModel, Field


class AssetCreate(BaseModel):
    title: str
    base_caption: str
    media_type: str = "text"
    language: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class AssetResponse(BaseModel):
    id: int
    title: str
    media_type: str
    file_path: str | None = None
    base_caption: str | None = None
    language: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
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
    section: str | None = None


class VariantUpdate(BaseModel):
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    section: str | None = None
    status: str | None = None


class VariantResponse(BaseModel):
    id: int
    asset_id: int
    platform: str
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    media_path: str | None = None
    section: str | None = None
    status: str
    account_id: int | None = None
    account_name: str | None = None
    generated_by: str | None = None

    model_config = {"from_attributes": True}


class GenerateVariantsRequest(BaseModel):
    account_ids: list[int]


class GenerateVariantErrorItem(BaseModel):
    account_id: int
    detail: str


class GenerateVariantsResponse(BaseModel):
    variants: list[VariantResponse]
    errors: list[GenerateVariantErrorItem] = Field(default_factory=list)
