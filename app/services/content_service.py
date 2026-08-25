import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ContentAsset, ContentVariant
from app.platforms import require_platform


class ContentService:
    def _content_root(self) -> Path:
        root = settings.data_dir / "content"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def list_assets(self, db: Session) -> list[ContentAsset]:
        return db.query(ContentAsset).order_by(ContentAsset.id.desc()).all()

    def get_asset(self, db: Session, asset_id: int) -> ContentAsset | None:
        return db.query(ContentAsset).filter(ContentAsset.id == asset_id).first()

    def create_asset(
        self,
        db: Session,
        *,
        title: str,
        media_type: str,
        base_caption: str | None = None,
        language: str | None = None,
        category: str | None = None,
    ) -> ContentAsset:
        asset = ContentAsset(
            title=title,
            media_type=media_type,
            base_caption=base_caption,
            language=language,
            category=category,
            status="DRAFT",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    def save_upload(self, db: Session, asset: ContentAsset, filename: str, data: bytes) -> ContentAsset:
        asset_dir = self._content_root() / str(asset.id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        dest = asset_dir / filename
        dest.write_bytes(data)
        rel = f"content/{asset.id}/{filename}"
        asset.file_path = rel
        asset.status = "READY"
        db.commit()
        db.refresh(asset)
        return asset

    def resolve_file_path(self, rel_path: str) -> Path:
        return settings.data_dir / rel_path

    def list_variants(self, db: Session, asset_id: int | None = None) -> list[ContentVariant]:
        query = db.query(ContentVariant).order_by(ContentVariant.id.desc())
        if asset_id is not None:
            query = query.filter(ContentVariant.asset_id == asset_id)
        return query.all()

    def get_variant(self, db: Session, variant_id: int) -> ContentVariant | None:
        return db.query(ContentVariant).filter(ContentVariant.id == variant_id).first()

    def create_variant(
        self,
        db: Session,
        *,
        asset_id: int,
        platform: str,
        title: str | None,
        caption: str | None,
        hashtags: list[str] | None = None,
        media_path: str | None = None,
        extra: dict | None = None,
    ) -> ContentVariant:
        asset = self.get_asset(db, asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        require_platform(platform)
        if asset.file_path:
            file_path = self.resolve_file_path(asset.file_path)
            if not file_path.exists():
                raise ValueError("Asset file missing on disk")

        variant = ContentVariant(
            asset_id=asset_id,
            platform=platform.lower(),
            title=title,
            caption=caption,
            hashtags_json=json.dumps(hashtags or []),
            media_path=media_path or asset.file_path,
            extra_json=json.dumps(extra or {}),
            status="READY",
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)
        return variant

    def update_variant(
        self,
        db: Session,
        variant: ContentVariant,
        *,
        title: str | None = None,
        caption: str | None = None,
        hashtags: list[str] | None = None,
        status: str | None = None,
    ) -> ContentVariant:
        if title is not None:
            variant.title = title
        if caption is not None:
            variant.caption = caption
        if hashtags is not None:
            variant.hashtags_json = json.dumps(hashtags)
        if status is not None:
            variant.status = status
        db.commit()
        db.refresh(variant)
        return variant


content_service = ContentService()
