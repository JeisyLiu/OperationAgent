import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.constants import AccountStatus
from app.llm import llm
from app.llm.types import BatchItem
from app.platforms import get_platform, require_platform
from app.schemas.accounts import AccountSkill
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.llm_model_service import llm_model_service


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

    def _normalize_section(self, platform_id: str, section: str | None) -> str:
        if not section:
            return ""
        platform = get_platform(platform_id)
        if not platform:
            return section
        choices = (
            platform.publish_options.get("section", {}).get("choices")
            if platform.publish_options
            else None
        )
        if not choices:
            return section
        return section if section in choices else ""

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
            "section": self._normalize_section(platform_id, payload.get("section")),
        }

    def generate_for_accounts(
        self,
        db: Session,
        *,
        asset_id: int,
        account_ids: list[int],
    ) -> GenerateVariantsResult:
        if not llm_model_service.list_enabled_configs(db):
            raise ValueError("AI settings not configured")

        asset = content_service.get_asset(db, asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        template = self._load_prompt_template()
        attachments = content_service._parse_attachments(asset)
        source_tags = ", ".join(attachments.get("tags") or [])
        variants: list = []
        errors: list[GenerateVariantError] = []
        batch_items: list[BatchItem] = []
        account_map: dict[int, object] = {}

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
            skill = account_service.resolve_skill(account) or AccountSkill()
            skill_json = skill.model_dump(exclude_none=True)
            section_options = platform.publish_options.get("section", {}) if platform else {}
            prompt = template.format(
                asset_title=asset.title,
                base_caption=asset.base_caption or "",
                source_tags=source_tags or "(none)",
                account_name=account.account_name,
                platform=account.platform,
                persona=account_service.resolve_persona(account),
                skill_json=json.dumps(skill_json, ensure_ascii=False),
                variant_schema=json.dumps(platform.variant_schema if platform else {}, ensure_ascii=False),
                section_options=json.dumps(section_options, ensure_ascii=False),
            )
            messages = [
                {"role": "system", "content": "You output platform-tailored social post JSON only."},
                {"role": "user", "content": prompt},
            ]
            batch_items.append(BatchItem(key=account_id, messages=messages))
            account_map[account_id] = account

        if batch_items:
            batch_results = llm.chat_batch(
                [(item.key, item.messages) for item in batch_items],
                max_tokens=800,
            )
            succeeded_account_ids: list[int] = []
            pending_creates: list[tuple[object, dict]] = []
            for result in batch_results:
                account_id = result.key
                account = account_map.get(account_id)
                if account is None:
                    continue
                if not result.ok:
                    errors.append(
                        GenerateVariantError(account_id=account_id, detail=result.error or "LLM failed")
                    )
                    continue
                try:
                    parsed = self._apply_schema_limits(
                        account.platform, self._parse_llm_json(result.text or "")
                    )
                    extra = {
                        "account_id": account.id,
                        "generated_by": "skill",
                        "account_name": account.account_name,
                    }
                    if parsed.get("section"):
                        extra["section"] = parsed["section"]
                    pending_creates.append((account, {**parsed, "_extra": extra}))
                    succeeded_account_ids.append(account.id)
                except Exception as exc:
                    errors.append(GenerateVariantError(account_id=account_id, detail=str(exc)))

            # Only replace drafts for accounts that generated successfully
            if succeeded_account_ids:
                content_service.delete_skill_drafts_for_accounts(
                    db,
                    asset_id=asset_id,
                    account_ids=succeeded_account_ids,
                )
            for account, parsed in pending_creates:
                try:
                    variant = content_service.create_variant(
                        db,
                        asset_id=asset_id,
                        platform=account.platform,
                        title=parsed.get("title"),
                        caption=parsed.get("caption"),
                        hashtags=parsed.get("hashtags"),
                        extra=parsed.get("_extra"),
                        status="DRAFT",
                    )
                    variants.append(variant)
                except Exception as exc:
                    errors.append(GenerateVariantError(account_id=account.id, detail=str(exc)))

        return GenerateVariantsResult(variants=variants, errors=errors)


content_generate_service = ContentGenerateService()
