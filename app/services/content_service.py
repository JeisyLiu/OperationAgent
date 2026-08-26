import json
from pathlib import Path

from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ContentAsset, ContentVariant
from app.platforms import require_platform

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}


class ContentService:
    def _content_root(self) -> Path:
        root = settings.data_dir / "content"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _parse_attachments(self, asset: ContentAsset) -> dict:
        if not asset.attachments_json:
            return {"images": [], "tags": []}
        try:
            data = json.loads(asset.attachments_json)
        except json.JSONDecodeError:
            return {"images": [], "tags": []}
        return {
            "images": list(data.get("images") or []),
            "tags": list(data.get("tags") or []),
        }

    def _write_attachments(self, asset: ContentAsset, *, images: list[str] | None = None, tags: list[str] | None = None) -> None:
        current = self._parse_attachments(asset)
        if images is not None:
            current["images"] = images
        if tags is not None:
            current["tags"] = tags
        asset.attachments_json = json.dumps(current)

    def _infer_media_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in IMAGE_EXTENSIONS:
            return "image"
        return "text"

    def list_assets(self, db: Session) -> list[ContentAsset]:
        return db.query(ContentAsset).order_by(ContentAsset.id.desc()).all()

    def get_asset(self, db: Session, asset_id: int) -> ContentAsset | None:
        return db.query(ContentAsset).filter(ContentAsset.id == asset_id).first()

    def asset_to_dict(self, asset: ContentAsset) -> dict:
        attachments = self._parse_attachments(asset)
        return {
            "id": asset.id,
            "title": asset.title,
            "media_type": asset.media_type,
            "file_path": asset.file_path,
            "base_caption": asset.base_caption,
            "language": asset.language,
            "category": asset.category,
            "tags": attachments["tags"],
            "images": attachments["images"],
            "status": asset.status,
            "created_at": asset.created_at,
        }

    def create_asset(
        self,
        db: Session,
        *,
        title: str,
        base_caption: str,
        media_type: str = "text",
        language: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> ContentAsset:
        asset = ContentAsset(
            title=title,
            media_type=media_type or "text",
            base_caption=base_caption,
            language=language,
            category=category,
            status="READY",
        )
        if tags:
            asset.attachments_json = json.dumps({"images": [], "tags": tags})
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
        media_type = self._infer_media_type(filename)
        if media_type == "video":
            asset.file_path = rel
            asset.media_type = "video"
        elif media_type == "image":
            attachments = self._parse_attachments(asset)
            images = list(attachments["images"])
            images.append(rel)
            self._write_attachments(asset, images=images)
            if not asset.file_path:
                asset.file_path = rel
                asset.media_type = "image"
        else:
            asset.file_path = rel
            asset.media_type = media_type
        asset.status = "READY"
        db.commit()
        db.refresh(asset)
        return asset

    def save_images(self, db: Session, asset: ContentAsset, files: list[tuple[str, bytes]]) -> ContentAsset:
        asset_dir = self._content_root() / str(asset.id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        attachments = self._parse_attachments(asset)
        images = list(attachments["images"])
        for filename, data in files:
            dest = asset_dir / filename
            dest.write_bytes(data)
            rel = f"content/{asset.id}/{filename}"
            images.append(rel)
            if not asset.file_path:
                asset.file_path = rel
                asset.media_type = "image"
        self._write_attachments(asset, images=images)
        asset.status = "READY"
        db.commit()
        db.refresh(asset)
        return asset

    def resolve_file_path(self, rel_path: str) -> Path:
        return settings.data_dir / rel_path

    def list_variants(self, db: Session, asset_id: int | None = None) -> list[ContentVariant]:
        items, _ = self.search_variants(db, asset_id=asset_id, page=1, page_size=10_000)
        return items

    def search_variants(
        self,
        db: Session,
        *,
        variant_id: int | None = None,
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
    ) -> tuple[list[ContentVariant], int]:
        query = db.query(ContentVariant)

        if variant_id is not None:
            query = query.filter(ContentVariant.id == variant_id)
        if asset_id is not None:
            query = query.filter(ContentVariant.asset_id == asset_id)
        if platform is not None:
            query = query.filter(ContentVariant.platform == platform.lower())
        if status is not None:
            query = query.filter(ContentVariant.status == status)
        if account_id is not None:
            query = query.filter(
                cast(func.json_extract(ContentVariant.extra_json, "$.account_id"), Integer) == account_id
            )
        if generated_by is not None:
            query = query.filter(
                func.json_extract(ContentVariant.extra_json, "$.generated_by") == generated_by
            )
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(ContentVariant.title.like(like), ContentVariant.caption.like(like))
            )

        sort_columns = {
            "id": ContentVariant.id,
            "asset_id": ContentVariant.asset_id,
            "platform": ContentVariant.platform,
            "status": ContentVariant.status,
        }
        sort_col = sort_columns.get(sort, ContentVariant.id)
        if order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def delete_variant(self, db: Session, variant: ContentVariant) -> None:
        if variant.status != "DRAFT":
            raise ValueError("Only DRAFT variants can be deleted")
        db.delete(variant)
        db.commit()

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
        status: str = "READY",
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
            status=status,
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)
        return variant

    def delete_skill_drafts_for_accounts(
        self,
        db: Session,
        *,
        asset_id: int,
        account_ids: list[int],
    ) -> int:
        """Remove previous skill-generated drafts for the same asset+accounts."""
        if not account_ids:
            return 0
        account_set = set(account_ids)
        rows = (
            db.query(ContentVariant)
            .filter(ContentVariant.asset_id == asset_id)
            .all()
        )
        deleted = 0
        for row in rows:
            try:
                extra = json.loads(row.extra_json or "{}")
            except json.JSONDecodeError:
                continue
            if extra.get("generated_by") != "skill":
                continue
            if extra.get("account_id") not in account_set:
                continue
            db.delete(row)
            deleted += 1
        if deleted:
            db.commit()
        return deleted

    def update_variant(
        self,
        db: Session,
        variant: ContentVariant,
        *,
        title: str | None = None,
        caption: str | None = None,
        hashtags: list[str] | None = None,
        section: str | None = None,
        status: str | None = None,
        extra_updates: dict | None = None,
    ) -> ContentVariant:
        if title is not None:
            variant.title = title
        if caption is not None:
            variant.caption = caption
        if hashtags is not None:
            variant.hashtags_json = json.dumps(hashtags)
        if section is not None or extra_updates:
            extra = {}
            if variant.extra_json:
                try:
                    extra = json.loads(variant.extra_json)
                except json.JSONDecodeError:
                    extra = {}
            if section is not None:
                extra["section"] = section
            if extra_updates:
                extra.update(extra_updates)
            variant.extra_json = json.dumps(extra)
        if status is not None:
            variant.status = status
        db.commit()
        db.refresh(variant)
        return variant


content_service = ContentService()
