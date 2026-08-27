import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.constants import AccountStatus
from app.db.models import ContentVariant
from app.llm import llm
from app.llm.types import BatchItem, BatchResult
from app.platforms import get_platform, require_platform
from app.schemas.accounts import AccountSkill
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.llm_model_service import llm_model_service
from app.services.operation_service import operation_service


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
        if value is None:
            return value
        if max_length is None:
            return value
        if max_length <= 0:
            return ""
        return value[:max_length]

    def _normalize_section(self, platform_id: str, section: str | None) -> str:
        if not section:
            return ""
        value = str(section).strip()
        if not value:
            return ""
        # Keep platform suggestions as soft guidance; custom values are allowed.
        return value[:64]

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

    def _title_required(self, platform_id: str) -> bool:
        platform = get_platform(platform_id)
        if not platform:
            return False
        title_schema = platform.variant_schema.get("title") or {}
        max_length = title_schema.get("max_length")
        if max_length is not None and max_length <= 0:
            return False
        return bool(title_schema.get("required")) or (max_length is not None and max_length > 0)

    def _is_too_similar_to_source(
        self,
        *,
        platform_id: str,
        parsed: dict,
        asset_title: str,
        base_caption: str,
    ) -> bool:
        title = (parsed.get("title") or "").strip()
        caption = (parsed.get("caption") or "").strip()
        src_title = (asset_title or "").strip()
        src_caption = (base_caption or "").strip()
        if caption and src_caption and caption == src_caption:
            return True
        if self._title_required(platform_id) and title and src_title and title == src_title:
            return True
        return False

    def _skill_snapshot(self, account, db: Session) -> tuple[dict, str]:
        skill = account_service.resolve_skill(account, db) or AccountSkill()
        persona = account_service.resolve_persona(account, db) or ""
        return skill.model_dump(exclude_none=True), persona

    def _input_snapshot(self, asset, source_tags: str) -> dict:
        return {
            "asset_title": asset.title,
            "base_caption": asset.base_caption or "",
            "source_tags": source_tags or "(none)",
        }

    def _usage_fields(self, result: BatchResult) -> dict:
        usage = result.usage
        if usage is None:
            return {
                "model_id": result.model_id,
                "model_alias": result.model_alias,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }
        return {
            "model_id": result.model_id,
            "model_alias": result.model_alias,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    def _record_step(
        self,
        db: Session,
        *,
        run_id: int | None,
        account,
        attempt: int,
        messages: list[dict],
        result: BatchResult | None,
        parsed: dict | None,
        status: str,
        error_message: str | None = None,
        duration_ms: int | None = None,
        variant_id: int | None = None,
    ) -> int | None:
        if run_id is None:
            return None
        skill, persona = self._skill_snapshot(account, db)
        usage = self._usage_fields(result) if result else {}
        step = operation_service.add_step(
            db,
            run_id=run_id,
            account_id=account.id,
            platform=account.platform,
            status=status,
            attempt=attempt,
            messages=messages,
            response_text=result.text if result else None,
            parsed=parsed,
            skill=skill,
            persona=persona,
            variant_id=variant_id,
            error_message=error_message,
            duration_ms=duration_ms,
            **usage,
        )
        return step.id

    def _build_prompt(
        self,
        *,
        template: str,
        asset,
        account,
        source_tags: str,
        db: Session,
    ) -> str:
        platform = get_platform(account.platform)
        skill = account_service.resolve_skill(account, db) or AccountSkill()
        skill_json = skill.model_dump(exclude_none=True)
        section_options = platform.publish_options.get("section", {}) if platform else {}
        return template.format(
            asset_title=asset.title,
            base_caption=asset.base_caption or "",
            source_tags=source_tags or "(none)",
            account_name=account.account_name,
            platform=account.platform,
            persona=account_service.resolve_persona(account, db),
            skill_json=json.dumps(skill_json, ensure_ascii=False),
            variant_schema=json.dumps(platform.variant_schema if platform else {}, ensure_ascii=False),
            section_options=json.dumps(section_options, ensure_ascii=False),
        )

    def _messages_for_account(
        self,
        *,
        template: str,
        asset,
        account,
        source_tags: str,
        db: Session,
        rewrite_hint: str | None = None,
    ) -> list[dict]:
        prompt = self._build_prompt(
            template=template,
            asset=asset,
            account=account,
            source_tags=source_tags,
            db=db,
        )
        if rewrite_hint:
            prompt = f"{prompt}\n\n## Extra rewrite guidance\n{rewrite_hint}"
        return [
            {
                "role": "system",
                "content": (
                    "You output platform-tailored social post JSON only. "
                    "Always rewrite title and caption; never copy the source text verbatim."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _parse_and_normalize(
        self,
        *,
        platform_id: str,
        text: str,
        asset_title: str,
        base_caption: str,
    ) -> dict:
        parsed = self._apply_schema_limits(platform_id, self._parse_llm_json(text or ""))
        if self._is_too_similar_to_source(
            platform_id=platform_id,
            parsed=parsed,
            asset_title=asset_title,
            base_caption=base_caption,
        ):
            raise ValueError("Generated copy too similar to source; rewrite required")
        return parsed

    def _call_llm(
        self,
        db: Session,
        *,
        run_id: int | None,
        account,
        messages: list[dict],
        attempt: int,
        asset,
    ) -> BatchResult:
        started = time.monotonic()
        results = llm.chat_batch([(account.id, messages)], max_tokens=800)
        duration_ms = int((time.monotonic() - started) * 1000)
        if not results:
            self._record_step(
                db,
                run_id=run_id,
                account=account,
                attempt=attempt,
                messages=messages,
                result=None,
                parsed=None,
                status="failed",
                error_message="LLM returned no result",
                duration_ms=duration_ms,
            )
            raise ValueError("LLM returned no result")
        result = results[0]
        if not result.ok:
            self._record_step(
                db,
                run_id=run_id,
                account=account,
                attempt=attempt,
                messages=messages,
                result=result,
                parsed=None,
                status="failed",
                error_message=result.error or "LLM failed",
                duration_ms=duration_ms,
            )
            raise ValueError(result.error or "LLM failed")
        result._duration_ms = duration_ms  # type: ignore[attr-defined]
        return result

    def _generate_payload_for_account(
        self,
        db: Session,
        *,
        asset,
        account,
        source_tags: str,
        template: str | None = None,
        retry_on_similar: bool = True,
        run_id: int | None = None,
    ) -> dict:
        template = template or self._load_prompt_template()
        messages = self._messages_for_account(
            template=template,
            asset=asset,
            account=account,
            source_tags=source_tags,
            db=db,
        )
        result = self._call_llm(
            db, run_id=run_id, account=account, messages=messages, attempt=1, asset=asset
        )
        duration_ms = getattr(result, "_duration_ms", None)

        try:
            parsed = self._parse_and_normalize(
                platform_id=account.platform,
                text=result.text or "",
                asset_title=asset.title,
                base_caption=asset.base_caption or "",
            )
            self._record_step(
                db,
                run_id=run_id,
                account=account,
                attempt=1,
                messages=messages,
                result=result,
                parsed=parsed,
                status="success",
                duration_ms=duration_ms,
            )
            return parsed
        except ValueError as first_exc:
            self._record_step(
                db,
                run_id=run_id,
                account=account,
                attempt=1,
                messages=messages,
                result=result,
                parsed=None,
                status="failed",
                error_message=str(first_exc),
                duration_ms=duration_ms,
            )
            if not retry_on_similar or "too similar" not in str(first_exc):
                raise
            retry_messages = self._messages_for_account(
                template=template,
                asset=asset,
                account=account,
                source_tags=source_tags,
                db=db,
                rewrite_hint=(
                    "Previous draft copied the source too closely. "
                    "Produce a clearly different title and caption while keeping the topic."
                ),
            )
            retry_result = self._call_llm(
                db,
                run_id=run_id,
                account=account,
                messages=retry_messages,
                attempt=2,
                asset=asset,
            )
            retry_duration = getattr(retry_result, "_duration_ms", None)
            parsed = self._parse_and_normalize(
                platform_id=account.platform,
                text=retry_result.text or "",
                asset_title=asset.title,
                base_caption=asset.base_caption or "",
            )
            self._record_step(
                db,
                run_id=run_id,
                account=account,
                attempt=2,
                messages=retry_messages,
                result=retry_result,
                parsed=parsed,
                status="success",
                duration_ms=retry_duration,
            )
            return parsed

    def _finalize_run_status(
        self,
        *,
        succeeded: int,
        failed: int,
        total: int,
    ) -> str:
        if succeeded and failed:
            return "partial"
        if succeeded:
            return "success"
        return "failed"

    def generate_for_accounts(
        self,
        db: Session,
        *,
        asset_id: int,
        account_ids: list[int],
        replace_drafts: bool = True,
    ) -> GenerateVariantsResult:
        if not llm_model_service.list_enabled_configs(db):
            raise ValueError("AI settings not configured")

        asset = content_service.get_asset(db, asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        template = self._load_prompt_template()
        attachments = content_service._parse_attachments(asset)
        source_tags = ", ".join(attachments.get("tags") or [])
        input_snapshot = self._input_snapshot(asset, source_tags)

        run = operation_service.create_run(
            db,
            kind="generate",
            asset_id=asset_id,
            account_ids=account_ids,
            summary=f"生成内容包 · {len(account_ids)} 账号",
            input_snapshot=input_snapshot,
        )
        run_id = run.id

        variants: list = []
        errors: list[GenerateVariantError] = []
        batch_items: list[BatchItem] = []
        account_map: dict[int, object] = {}
        messages_map: dict[int, list[dict]] = {}

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
                require_platform(account.platform, db=db)
            except Exception as exc:
                errors.append(GenerateVariantError(account_id=account_id, detail=str(exc)))
                continue

            messages = self._messages_for_account(
                template=template,
                asset=asset,
                account=account,
                source_tags=source_tags,
                db=db,
            )
            batch_items.append(BatchItem(key=account_id, messages=messages))
            account_map[account_id] = account
            messages_map[account_id] = messages

        if batch_items:
            started = time.monotonic()
            batch_results = llm.chat_batch(
                [(item.key, item.messages) for item in batch_items],
                max_tokens=800,
            )
            batch_duration = int((time.monotonic() - started) * 1000)
            per_account_duration = batch_duration // max(len(batch_results), 1)

            succeeded_account_ids: list[int] = []
            pending_creates: list[tuple[object, dict]] = []
            retry_accounts: list[tuple[object, list[dict]]] = []

            for result in batch_results:
                account_id = result.key
                account = account_map.get(account_id)
                if account is None:
                    continue
                messages = messages_map.get(account_id, [])
                if not result.ok:
                    errors.append(
                        GenerateVariantError(account_id=account_id, detail=result.error or "LLM failed")
                    )
                    self._record_step(
                        db,
                        run_id=run_id,
                        account=account,
                        attempt=1,
                        messages=messages,
                        result=result,
                        parsed=None,
                        status="failed",
                        error_message=result.error or "LLM failed",
                        duration_ms=per_account_duration,
                    )
                    continue
                try:
                    parsed = self._parse_and_normalize(
                        platform_id=account.platform,
                        text=result.text or "",
                        asset_title=asset.title,
                        base_caption=asset.base_caption or "",
                    )
                    self._record_step(
                        db,
                        run_id=run_id,
                        account=account,
                        attempt=1,
                        messages=messages,
                        result=result,
                        parsed=parsed,
                        status="success",
                        duration_ms=per_account_duration,
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
                except ValueError as exc:
                    if "too similar" in str(exc):
                        self._record_step(
                            db,
                            run_id=run_id,
                            account=account,
                            attempt=1,
                            messages=messages,
                            result=result,
                            parsed=None,
                            status="failed",
                            error_message=str(exc),
                            duration_ms=per_account_duration,
                        )
                        retry_messages = self._messages_for_account(
                            template=template,
                            asset=asset,
                            account=account,
                            source_tags=source_tags,
                            db=db,
                            rewrite_hint=(
                                "Previous draft copied the source too closely. "
                                "Produce a clearly different title and caption while keeping the topic."
                            ),
                        )
                        retry_accounts.append((account, retry_messages))
                    else:
                        errors.append(GenerateVariantError(account_id=account_id, detail=str(exc)))

            if retry_accounts:
                retry_started = time.monotonic()
                retry_results = llm.chat_batch(
                    [(account.id, msgs) for account, msgs in retry_accounts],
                    max_tokens=800,
                )
                retry_duration = int((time.monotonic() - retry_started) * 1000)
                per_retry = retry_duration // max(len(retry_results), 1)
                retry_msg_map = {account.id: msgs for account, msgs in retry_accounts}

                for result in retry_results:
                    account = account_map.get(result.key)
                    if account is None:
                        continue
                    messages = retry_msg_map.get(account.id, [])
                    if not result.ok:
                        errors.append(
                            GenerateVariantError(
                                account_id=account.id, detail=result.error or "LLM retry failed"
                            )
                        )
                        self._record_step(
                            db,
                            run_id=run_id,
                            account=account,
                            attempt=2,
                            messages=messages,
                            result=result,
                            parsed=None,
                            status="failed",
                            error_message=result.error or "LLM retry failed",
                            duration_ms=per_retry,
                        )
                        continue
                    try:
                        parsed = self._parse_and_normalize(
                            platform_id=account.platform,
                            text=result.text or "",
                            asset_title=asset.title,
                            base_caption=asset.base_caption or "",
                        )
                        self._record_step(
                            db,
                            run_id=run_id,
                            account=account,
                            attempt=2,
                            messages=messages,
                            result=result,
                            parsed=parsed,
                            status="success",
                            duration_ms=per_retry,
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
                        errors.append(GenerateVariantError(account_id=account.id, detail=str(exc)))
                        self._record_step(
                            db,
                            run_id=run_id,
                            account=account,
                            attempt=2,
                            messages=messages,
                            result=result,
                            parsed=None,
                            status="failed",
                            error_message=str(exc),
                            duration_ms=per_retry,
                        )

            if replace_drafts and succeeded_account_ids:
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

        variant_ids = [v.id for v in variants]
        status = self._finalize_run_status(
            succeeded=len(variants),
            failed=len(errors),
            total=len(account_ids),
        )
        error_msg = None
        if errors and not variants:
            error_msg = errors[0].detail
        operation_service.finalize_run(
            db,
            run,
            status=status,
            variant_ids=variant_ids,
            error_message=error_msg,
        )

        return GenerateVariantsResult(variants=variants, errors=errors)

    def rewrite_variant(self, db: Session, variant_id: int) -> ContentVariant:
        if not llm_model_service.list_enabled_configs(db):
            raise ValueError("AI settings not configured")

        variant = content_service.get_variant(db, variant_id)
        if variant is None:
            raise ValueError("Variant not found")

        extra = {}
        if variant.extra_json:
            try:
                extra = json.loads(variant.extra_json)
            except json.JSONDecodeError:
                extra = {}
        account_id = extra.get("account_id")
        if not account_id:
            raise ValueError("Variant has no linked account; cannot rewrite with skill")

        account = account_service.get(db, int(account_id))
        if account is None:
            raise ValueError("Linked account not found")
        if account.status != AccountStatus.ACTIVE.value:
            raise ValueError("Account must be ACTIVE")
        require_platform(account.platform, db=db)

        asset = content_service.get_asset(db, variant.asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        attachments = content_service._parse_attachments(asset)
        source_tags = ", ".join(attachments.get("tags") or [])
        input_snapshot = self._input_snapshot(asset, source_tags)

        run = operation_service.create_run(
            db,
            kind="rewrite",
            asset_id=asset.id,
            account_ids=[account.id],
            summary=f"LLM 重写内容包 #{variant_id}",
            input_snapshot=input_snapshot,
        )

        try:
            parsed = self._generate_payload_for_account(
                db,
                asset=asset,
                account=account,
                source_tags=source_tags,
                retry_on_similar=True,
                run_id=run.id,
            )
            updated = content_service.update_variant(
                db,
                variant,
                title=parsed.get("title") or "",
                caption=parsed.get("caption") or "",
                hashtags=parsed.get("hashtags") or [],
                section=parsed.get("section") or "",
                extra_updates={"rewritten_by": "llm"},
            )
            operation_service.finalize_run(
                db,
                run,
                status="success",
                variant_ids=[updated.id],
            )
            return updated
        except Exception as exc:
            operation_service.finalize_run(
                db,
                run,
                status="failed",
                variant_ids=[],
                error_message=str(exc),
            )
            raise


content_generate_service = ContentGenerateService()
