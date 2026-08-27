import json
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import AccountStatus
from app.db.models import Account
from app.platforms import get_platform_default_persona, get_platform_default_skill
from app.schemas.accounts import AccountSkill
from app.skills.loader import (
    get_overlay,
    get_role,
    merge_skill_layers,
    merge_tag_skills,
    preview_resolved,
)


class AccountService:
    def _profiles_root(self) -> Path:
        root = settings.data_dir / "profiles"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def parse_role_tags(self, account: Account) -> list[str]:
        if not account.role_tags_json:
            return []
        try:
            data = json.loads(account.role_tags_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [str(item) for item in data if item]

    def _skill_from_dict(self, data: dict | None) -> AccountSkill | None:
        if not data:
            return None
        return AccountSkill.model_validate(data)

    def _merge_skills(self, base: AccountSkill, override: AccountSkill | None) -> AccountSkill:
        if override is None:
            return base
        return AccountSkill(
            tone=override.tone or base.tone,
            audience=override.audience or base.audience,
            language=override.language or base.language,
            taboos=override.taboos if override.taboos else base.taboos,
            cta=override.cta or base.cta,
            topics=override.topics if override.topics else base.topics,
            hashtag_style=override.hashtag_style or base.hashtag_style,
            extra_prompt=override.extra_prompt or base.extra_prompt,
            content_goals=override.content_goals if override.content_goals else base.content_goals,
            claim_policy=override.claim_policy or base.claim_policy,
            structure=override.structure if override.structure else base.structure,
            evidence_style=override.evidence_style or base.evidence_style,
            disclaimer=override.disclaimer or base.disclaimer,
            interaction_style=override.interaction_style or base.interaction_style,
        )

    def _template_skill_layers(self, account: Account, db: Session | None = None) -> list[AccountSkill | None]:
        platform_skill = self._skill_from_dict(get_platform_default_skill(account.platform))
        role = get_role(account.role_id, db) if account.role_id else None
        role_skill = self._skill_from_dict(role.skill) if role else None
        overlay = get_overlay(account.role_id, account.platform, db) if account.role_id else None
        overlay_skill = self._skill_from_dict(overlay.skill) if overlay else None
        tag_skill = merge_tag_skills(self.parse_role_tags(account))
        return [platform_skill, role_skill, overlay_skill, tag_skill]

    def resolve_template_skill(self, account: Account, db: Session | None = None) -> AccountSkill | None:
        return merge_skill_layers(*self._template_skill_layers(account, db))

    def resolve_skill(self, account: Account, db: Session | None = None) -> AccountSkill | None:
        merged = merge_skill_layers(*self._template_skill_layers(account, db), self.parse_skill(account))
        if merged is None:
            return None
        if not merged.language and account.language:
            return merged.model_copy(update={"language": account.language})
        return merged

    def resolve_persona(self, account: Account, db: Session | None = None) -> str:
        if account.persona:
            return account.persona
        preview = preview_resolved(
            platform=account.platform,
            role_id=account.role_id,
            role_tags=self.parse_role_tags(account),
            db=db,
        )
        return preview.get("persona") or get_platform_default_persona(account.platform) or ""

    def resolve_role_display_name(self, account: Account, db: Session | None = None) -> str | None:
        if not account.role_id:
            return None
        role = get_role(account.role_id, db)
        return role.display_name if role else account.role_id

    def validate_role_id(self, role_id: str | None, db: Session | None = None) -> None:
        if role_id is None:
            return
        if get_role(role_id, db) is None:
            raise ValueError(f"Unknown role_id: {role_id}")

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
        elif "skill" in base:
            del base["skill"]
        return json.dumps(base) if base else None

    def clear_skill_override(self, account: Account) -> None:
        if not account.metadata_json:
            return
        try:
            base = json.loads(account.metadata_json)
        except json.JSONDecodeError:
            return
        if "skill" not in base:
            return
        del base["skill"]
        account.metadata_json = json.dumps(base) if base else None

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
        role_id: str | None = None,
        role_tags: list[str] | None = None,
        skill: AccountSkill | None = None,
    ) -> Account:
        self.validate_role_id(role_id, db)
        profile_name = f"{platform}_{uuid.uuid4().hex[:8]}"
        profile_rel = f"profiles/{profile_name}"
        profile_path = self._profiles_root() / profile_name
        profile_path.mkdir(parents=True, exist_ok=True)

        metadata_json = None
        if skill is not None:
            metadata_json = self.skill_to_metadata(skill)

        account = Account(
            platform=platform,
            account_name=account_name,
            browser_profile=profile_rel,
            persona=persona,
            language=language,
            description=description,
            role_id=role_id,
            role_tags_json=json.dumps(role_tags or []) if role_tags else None,
            metadata_json=metadata_json,
            status=AccountStatus.PENDING_LOGIN.value,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        if account.language is None:
            resolved = self.resolve_skill(account, db)
            if resolved and resolved.language:
                account.language = resolved.language
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
        role_id: str | None = None,
        role_tags: list[str] | None = None,
        skill: AccountSkill | None = None,
        clear_skill_override: bool = False,
        metadata_json: dict | None = None,
    ) -> Account:
        if role_id is not None:
            self.validate_role_id(role_id, db)
            account.role_id = role_id or None
        if role_tags is not None:
            account.role_tags_json = json.dumps(role_tags) if role_tags else None
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
        if clear_skill_override:
            self.clear_skill_override(account)
        if skill is not None:
            account.metadata_json = self.skill_to_metadata(skill, account)
            if skill.language and language is None:
                account.language = skill.language
        if metadata_json is not None:
            account.metadata_json = json.dumps(metadata_json)
        db.commit()
        db.refresh(account)
        return account

    def set_role(
        self,
        db: Session,
        account: Account,
        *,
        role_id: str,
        replace_skill: bool = False,
    ) -> Account:
        self.validate_role_id(role_id, db)
        account.role_id = role_id
        if replace_skill:
            self.clear_skill_override(account)
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
