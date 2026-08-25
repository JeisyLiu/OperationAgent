import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import LlmModel
from app.services.crypto import decrypt_text, encrypt_text, mask_api_key

SUPPORTED_PROVIDERS = {"openai", "qwen"}


@dataclass
class LlmModelConfig:
    id: int
    alias: str
    provider: str
    base_url: str | None
    model: str | None
    api_key: str | None
    enabled: bool
    priority: int
    max_concurrency: int
    timeout_sec: int
    extra: dict


@dataclass
class LlmModelPublic:
    id: int
    alias: str
    provider: str
    base_url: str | None
    model: str | None
    api_key_masked: str | None
    enabled: bool
    priority: int
    max_concurrency: int
    timeout_sec: int
    updated_at: datetime | None


def _row_to_config(row: LlmModel) -> LlmModelConfig:
    extra: dict = {}
    if row.extra_json:
        try:
            extra = json.loads(row.extra_json)
        except json.JSONDecodeError:
            extra = {}
    api_key = decrypt_text(row.api_key_enc) if row.api_key_enc else None
    return LlmModelConfig(
        id=row.id,
        alias=row.alias,
        provider=row.provider.lower(),
        base_url=row.base_url,
        model=row.model,
        api_key=api_key,
        enabled=bool(row.enabled),
        priority=row.priority,
        max_concurrency=row.max_concurrency or 4,
        timeout_sec=row.timeout_sec or 60,
        extra=extra,
    )


def _row_to_public(row: LlmModel) -> LlmModelPublic:
    api_key = decrypt_text(row.api_key_enc) if row.api_key_enc else None
    return LlmModelPublic(
        id=row.id,
        alias=row.alias,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key_masked=mask_api_key(api_key),
        enabled=bool(row.enabled),
        priority=row.priority,
        max_concurrency=row.max_concurrency or 4,
        timeout_sec=row.timeout_sec or 60,
        updated_at=row.updated_at,
    )


class LlmModelService:
    def list_models(self, db: Session) -> list[LlmModelPublic]:
        rows = db.query(LlmModel).order_by(LlmModel.priority.asc(), LlmModel.id.asc()).all()
        return [_row_to_public(row) for row in rows]

    def get(self, db: Session, model_id: int) -> LlmModel | None:
        return db.query(LlmModel).filter(LlmModel.id == model_id).first()

    def get_config(self, db: Session, model_id: int) -> LlmModelConfig | None:
        row = self.get(db, model_id)
        return _row_to_config(row) if row else None

    def list_enabled_configs(self, db: Session) -> list[LlmModelConfig]:
        rows = (
            db.query(LlmModel)
            .filter(LlmModel.enabled == 1)
            .order_by(LlmModel.priority.asc(), LlmModel.id.asc())
            .all()
        )
        return [_row_to_config(row) for row in rows]

    def get_primary_config(self, db: Session) -> LlmModelConfig | None:
        configs = self.list_enabled_configs(db)
        return configs[0] if configs else None

    def create(
        self,
        db: Session,
        *,
        alias: str,
        provider: str,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        enabled: bool = True,
        priority: int = 0,
        max_concurrency: int = 4,
        timeout_sec: int = 60,
    ) -> LlmModelPublic:
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        row = LlmModel(
            alias=alias,
            provider=provider,
            base_url=base_url,
            model=model,
            api_key_enc=encrypt_text(api_key) if api_key else None,
            enabled=1 if enabled else 0,
            priority=priority,
            max_concurrency=max_concurrency,
            timeout_sec=timeout_sec,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_public(row)

    def update(
        self,
        db: Session,
        row: LlmModel,
        *,
        alias: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
        max_concurrency: int | None = None,
        timeout_sec: int | None = None,
    ) -> LlmModelPublic:
        if alias is not None:
            row.alias = alias
        if provider is not None:
            provider = provider.lower()
            if provider not in SUPPORTED_PROVIDERS:
                raise ValueError(f"Unsupported provider: {provider}")
            row.provider = provider
        if base_url is not None:
            row.base_url = base_url
        if model is not None:
            row.model = model
        if api_key is not None:
            row.api_key_enc = encrypt_text(api_key) if api_key else None
        if enabled is not None:
            row.enabled = 1 if enabled else 0
        if priority is not None:
            row.priority = priority
        if max_concurrency is not None:
            row.max_concurrency = max_concurrency
        if timeout_sec is not None:
            row.timeout_sec = timeout_sec
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        return _row_to_public(row)

    def delete(self, db: Session, row: LlmModel) -> None:
        db.delete(row)
        db.commit()

    def upsert_primary_legacy(
        self,
        db: Session,
        *,
        provider: str,
        base_url: str | None,
        model: str | None,
        api_key: str | None,
    ) -> LlmModelPublic:
        row = (
            db.query(LlmModel)
            .filter(LlmModel.enabled == 1)
            .order_by(LlmModel.priority.asc(), LlmModel.id.asc())
            .first()
        )
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            provider = "openai"
        if row is None:
            return self.create(
                db,
                alias="Default",
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
                enabled=True,
                priority=0,
            )
        return self.update(
            db,
            row,
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
        )


llm_model_service = LlmModelService()
