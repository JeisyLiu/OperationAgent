from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AiSettings
from app.services.crypto import decrypt_text, encrypt_text, mask_api_key


@dataclass
class AiSettingsDTO:
    provider: str
    base_url: str | None
    model: str | None
    api_key_masked: str | None
    updated_at: datetime | None


@dataclass
class AiSettingsSecrets:
    provider: str
    base_url: str | None
    model: str | None
    api_key: str | None


class SettingsService:
    def get_public(self, db: Session) -> AiSettingsDTO | None:
        row = db.query(AiSettings).order_by(AiSettings.id.desc()).first()
        if not row:
            return None
        api_key = decrypt_text(row.api_key_enc) if row.api_key_enc else None
        return AiSettingsDTO(
            provider=row.provider,
            base_url=row.base_url,
            model=row.model,
            api_key_masked=mask_api_key(api_key),
            updated_at=row.updated_at,
        )

    def get_secrets(self, db: Session) -> AiSettingsSecrets | None:
        row = db.query(AiSettings).order_by(AiSettings.id.desc()).first()
        if not row:
            return None
        api_key = decrypt_text(row.api_key_enc) if row.api_key_enc else None
        return AiSettingsSecrets(
            provider=row.provider,
            base_url=row.base_url,
            model=row.model,
            api_key=api_key,
        )

    def save(
        self,
        db: Session,
        *,
        provider: str,
        base_url: str | None,
        model: str | None,
        api_key: str | None,
    ) -> AiSettingsDTO:
        row = db.query(AiSettings).order_by(AiSettings.id.desc()).first()
        if row is None:
            row = AiSettings(provider=provider)
            db.add(row)

        row.provider = provider
        row.base_url = base_url
        row.model = model
        if api_key is not None:
            row.api_key_enc = encrypt_text(api_key)
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)

        public = self.get_public(db)
        assert public is not None
        return public


settings_service = SettingsService()
