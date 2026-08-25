import json
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import AccountStatus
from app.db.models import Account
from app.schemas.accounts import AccountSkill


class AccountService:
    def _profiles_root(self) -> Path:
        root = settings.data_dir / "profiles"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def parse_skill(self, account: Account) -> AccountSkill | None:
        if not account.metadata_json:
            return None
        try:
            data = json.loads(account.metadata_json)
        except json.JSONDecodeError:
            return None
        skill_data = data.get("skill")
        if not skill_data:
            return None
        return AccountSkill.model_validate(skill_data)

    def skill_to_metadata(self, skill: AccountSkill | None, existing: Account | None = None) -> str | None:
        if skill is None and existing is None:
            return None
        base: dict = {}
        if existing and existing.metadata_json:
            try:
                base = json.loads(existing.metadata_json)
            except json.JSONDecodeError:
                base = {}
        if skill is not None:
            base["skill"] = skill.model_dump(exclude_none=True)
        return json.dumps(base) if base else None

    def list_accounts(self, db: Session, platform: str | None = None) -> list[Account]:
        query = db.query(Account).order_by(Account.id.desc())
        if platform:
            query = query.filter(Account.platform == platform)
        return query.all()

    def get(self, db: Session, account_id: int) -> Account | None:
        return db.query(Account).filter(Account.id == account_id).first()

    def create(
        self,
        db: Session,
        *,
        platform: str,
        account_name: str,
        persona: str | None = None,
        language: str | None = None,
        description: str | None = None,
        skill: AccountSkill | None = None,
    ) -> Account:
        profile_name = f"{platform}_{uuid.uuid4().hex[:8]}"
        profile_rel = f"profiles/{profile_name}"
        profile_path = self._profiles_root() / profile_name
        profile_path.mkdir(parents=True, exist_ok=True)

        account = Account(
            platform=platform,
            account_name=account_name,
            browser_profile=profile_rel,
            persona=persona,
            language=language or (skill.language if skill else None),
            description=description,
            metadata_json=self.skill_to_metadata(skill),
            status=AccountStatus.PENDING_LOGIN.value,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def update(
        self,
        db: Session,
        account: Account,
        *,
        account_name: str | None = None,
        persona: str | None = None,
        language: str | None = None,
        description: str | None = None,
        status: str | None = None,
        skill: AccountSkill | None = None,
        metadata_json: dict | None = None,
    ) -> Account:
        if account_name is not None:
            account.account_name = account_name
        if persona is not None:
            account.persona = persona
        if language is not None:
            account.language = language
        if description is not None:
            account.description = description
        if status is not None:
            account.status = status
        if skill is not None:
            account.metadata_json = self.skill_to_metadata(skill, account)
            if skill.language and language is None:
                account.language = skill.language
        if metadata_json is not None:
            account.metadata_json = json.dumps(metadata_json)
        db.commit()
        db.refresh(account)
        return account

    def mark_active(self, db: Session, account: Account) -> Account:
        account.status = AccountStatus.ACTIVE.value
        db.commit()
        db.refresh(account)
        return account

    def delete(self, db: Session, account: Account) -> None:
        db.delete(account)
        db.commit()

    def resolve_profile_path(self, account: Account) -> Path:
        return settings.data_dir / account.browser_profile


account_service = AccountService()
