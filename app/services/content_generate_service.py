import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.constants import AccountStatus
from app.llm import client as llm_client
from app.platforms import get_platform, require_platform
from app.schemas.accounts import AccountSkill
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.settings_service import settings_service


@dataclass
class GenerateVariantError:
    account_id: int
    detail: str


@dataclass
class GenerateVariantsResult:
    variants: list
    errors: list[GenerateVariantError]


class ContentGenerateService:
    def _load_prompt_template(self) -> str:
        path = Path(__file__).resolve().parents[1] / "prompts" / "generate_variant.md"
        return path.read_text(encoding="utf-8")

    def _parse_llm_json(self, text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("LLM response is not valid JSON") from None
            return json.loads(match.group(0))

    def _truncate_field(self, value: str | None, max_length: int | None) -> str | None:
        if value is None or not max_length:
            return value
        return value[:max_length]

    def _apply_schema_limits(self, platform_id: str, payload: dict) -> dict:
        platform = get_platform(platform_id)
        schema = platform.variant_schema if platform else {}
        title = payload.get("title")
        caption = payload.get("caption")
        title_schema = schema.get("title", {})
        caption_schema = schema.get("caption", {})
        return {
            "title": self._truncate_field(title, title_schema.get("max_length")),
            "caption": self._truncate_field(caption, caption_schema.get("max_length")),
            "hashtags": payload.get("hashtags") or [],
        }

    def generate_for_accounts(
        self,
        db: Session,
        *,
        asset_id: int,
        account_ids: list[int],
    ) -> GenerateVariantsResult:
        secrets = settings_service.get_secrets(db)
        if secrets is None or not secrets.api_key:
            raise ValueError("AI settings not configured")

        asset = content_service.get_asset(db, asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        if not asset.file_path:
            raise ValueError("Asset file not uploaded yet")

        template = self._load_prompt_template()
        variants: list = []
        errors: list[GenerateVariantError] = []

        for account_id in account_ids:
            account = account_service.get(db, account_id)
            if account is None:
                errors.append(GenerateVariantError(account_id=account_id, detail="Account not found"))
                continue
            if account.status != AccountStatus.ACTIVE.value:
                errors.append(
                    GenerateVariantError(account_id=account_id, detail="Account must be ACTIVE")
                )
                continue
            try:
                require_platform(account.platform)
            except Exception as exc:
                errors.append(GenerateVariantError(account_id=account_id, detail=str(exc)))
                continue

            platform = get_platform(account.platform)
            skill = account_service.parse_skill(account) or AccountSkill()
            skill_json = skill.model_dump(exclude_none=True)
            prompt = template.format(
                asset_title=asset.title,
                base_caption=asset.base_caption or "",
                account_name=account.account_name,
                platform=account.platform,
                persona=account.persona or "",
                skill_json=json.dumps(skill_json, ensure_ascii=False),
                variant_schema=json.dumps(platform.variant_schema if platform else {}, ensure_ascii=False),
            )
            try:
                reply = llm_client.chat(
                    [
                        {"role": "system", "content": "You output platform-tailored social post JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    secrets,
                    max_tokens=800,
                )
                parsed = self._apply_schema_limits(account.platform, self._parse_llm_json(reply))
                variant = content_service.create_variant(
                    db,
                    asset_id=asset_id,
                    platform=account.platform,
                    title=parsed.get("title"),
                    caption=parsed.get("caption"),
                    hashtags=parsed.get("hashtags"),
                    extra={
                        "account_id": account.id,
                        "generated_by": "skill",
                        "account_name": account.account_name,
                    },
                )
                variants.append(variant)
            except Exception as exc:
                errors.append(GenerateVariantError(account_id=account_id, detail=str(exc)))

        return GenerateVariantsResult(variants=variants, errors=errors)


content_generate_service = ContentGenerateService()
