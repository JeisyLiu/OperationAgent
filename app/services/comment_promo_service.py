import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.base import AgentStatus, AgentTask
from app.agent.factory import resolve_adapter_for_platform
from app.constants import AccountStatus, RUNNING_JOB_STATUSES
from app.db.models import (
    OperationRun,
    PromoComment,
    PromoRun,
    PromoSeenUrl,
    PromoTarget,
    PublishJob,
)
from app.db.session import SessionLocal
from app.llm import llm
from app.platforms import get_platform
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.execution_log_service import SUBJECT_PROMO_RUN, execution_log_service
from app.services.operation_service import operation_service

logger = logging.getLogger(__name__)

PROMO_ALLOWED_PLATFORMS = frozenset({"rednote", "bilibili"})
PROMO_VIDEOS_PER_TAG = 5
PROMO_COMMENTS_PER_VIDEO = 5
PROMO_ACTIVE_STATUSES = frozenset({"pending", "discovering", "generating", "cancelling"})
PROMO_TERMINAL_STATUSES = frozenset({"ready", "partial", "failed", "cancelled"})
SEEN_SKIP_STATUSES = frozenset({"seen", "drafted", "commented"})


class CommentPromoService:
    _active_adapters: dict[int, object] = {}

    def _load_prompt(self, name: str) -> str:
        path = Path(__file__).resolve().parents[1] / "prompts" / name
        return path.read_text(encoding="utf-8")

    def _parse_json_blob(self, text: str) -> dict:
        text = (text or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("Response is not valid JSON") from None
            return json.loads(match.group(0))

    def _normalize_url(self, url: str) -> str:
        normalized = (url or "").strip()
        while normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized

    def _log_promo(
        self,
        db: Session,
        run_id: int,
        step: str,
        message: str | None = None,
        **kwargs,
    ):
        return execution_log_service.add_log(
            db,
            subject_type=SUBJECT_PROMO_RUN,
            subject_id=run_id,
            step=step,
            message=message,
            **kwargs,
        )

    def _get_seen_url(
        self,
        db: Session,
        *,
        account_id: int,
        platform: str,
        url: str,
    ) -> PromoSeenUrl | None:
        return (
            db.query(PromoSeenUrl)
            .filter(
                PromoSeenUrl.account_id == account_id,
                PromoSeenUrl.platform == platform,
                PromoSeenUrl.url == url,
            )
            .first()
        )

    def _upsert_seen_url(
        self,
        db: Session,
        *,
        account_id: int,
        platform: str,
        url: str,
        promo_run_id: int,
        status: str = "seen",
    ) -> PromoSeenUrl:
        now = datetime.utcnow()
        row = self._get_seen_url(db, account_id=account_id, platform=platform, url=url)
        if row is None:
            row = PromoSeenUrl(
                account_id=account_id,
                platform=platform,
                url=url,
                status=status,
                first_seen_at=now,
                last_seen_at=now,
                promo_run_id=promo_run_id,
            )
            db.add(row)
        else:
            row.last_seen_at = now
            row.promo_run_id = promo_run_id
            if status == "drafted" or row.status == "seen":
                row.status = status
        return row

    def _mark_url_drafted(
        self,
        db: Session,
        *,
        account_id: int,
        platform: str,
        url: str,
        promo_run_id: int,
    ) -> None:
        self._upsert_seen_url(
            db,
            account_id=account_id,
            platform=platform,
            url=self._normalize_url(url),
            promo_run_id=promo_run_id,
            status="drafted",
        )

    def _should_skip_url(self, db: Session, *, account_id: int, platform: str, url: str) -> bool:
        row = self._get_seen_url(
            db,
            account_id=account_id,
            platform=platform,
            url=self._normalize_url(url),
        )
        return row is not None and row.status in SEEN_SKIP_STATUSES

    def _should_cancel(self, db: Session, run_id: int) -> bool:
        run = db.query(PromoRun).filter(PromoRun.id == run_id).first()
        return run is not None and run.status in ("cancelling", "cancelled")

    def _stop_adapter_sync(self, adapter) -> None:
        try:
            asyncio.run(adapter.stop())
        except Exception:
            logger.exception("Failed to stop promo discover adapter")

    def _resolve_tags(self, db: Session, variant) -> list[str]:
        asset = content_service.get_asset(db, variant.asset_id)
        tags: list[str] = []
        if asset:
            attachments = content_service._parse_attachments(asset)
            tags = [t.strip() for t in attachments.get("tags") or [] if t.strip()]
        if not tags:
            tags = [
                h.strip().lstrip("#")
                for h in json.loads(variant.hashtags_json or "[]")
                if h and str(h).strip()
            ]
        seen: set[str] = set()
        unique: list[str] = []
        for tag in tags:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                unique.append(tag)
        return unique

    def _variant_account_id(self, variant) -> int | None:
        extra = json.loads(variant.extra_json or "{}")
        account_id = extra.get("account_id")
        return int(account_id) if account_id is not None else None

    def _account_busy(self, db: Session, account_id: int) -> bool:
        promo_active = (
            db.query(PromoRun)
            .filter(
                PromoRun.account_id == account_id,
                PromoRun.status.in_(list(PROMO_ACTIVE_STATUSES)),
            )
            .count()
        )
        if promo_active:
            return True
        job_active = (
            db.query(PublishJob)
            .filter(
                PublishJob.account_id == account_id,
                PublishJob.status.in_(list(RUNNING_JOB_STATUSES)),
            )
            .count()
        )
        return job_active > 0

    def validate_start(self, db: Session, variant_id: int) -> tuple:
        variant = content_service.get_variant(db, variant_id)
        if variant is None:
            raise ValueError("Variant not found")
        if variant.platform not in PROMO_ALLOWED_PLATFORMS:
            raise ValueError("评论推广仅支持小红书与 B 站")
        account_id = self._variant_account_id(variant)
        if account_id is None:
            raise ValueError("内容包未关联账号")
        account = account_service.get(db, account_id)
        if account is None:
            raise ValueError("Account not found")
        if account.status != AccountStatus.ACTIVE.value:
            raise ValueError("账号须为 ACTIVE 状态")
        if account.platform != variant.platform:
            raise ValueError("账号平台与内容包不一致")
        tags = self._resolve_tags(db, variant)
        if not tags:
            raise ValueError("请先给母帖补标签")
        if self._account_busy(db, account_id):
            raise ValueError("该账号有进行中的推广或发布任务，请稍后再试")
        return variant, account, tags

    def start_run(self, db: Session, variant_id: int) -> PromoRun:
        variant, account, tags = self.validate_start(db, variant_id)
        op_run = operation_service.create_run(
            db,
            kind="promo",
            asset_id=variant.asset_id,
            account_ids=[account.id],
            summary=f"评论推广 · {variant.platform} · {len(tags)} 标签",
            input_snapshot={
                "variant_id": variant.id,
                "platform": variant.platform,
                "tags": tags,
                "videos_per_tag": PROMO_VIDEOS_PER_TAG,
                "comments_per_video": PROMO_COMMENTS_PER_VIDEO,
            },
        )
        run = PromoRun(
            variant_id=variant.id,
            asset_id=variant.asset_id,
            account_id=account.id,
            platform=variant.platform,
            status="pending",
            tags_json=json.dumps(tags, ensure_ascii=False),
            operation_run_id=op_run.id,
            created_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        if op_run.input_json:
            try:
                snap = json.loads(op_run.input_json)
            except json.JSONDecodeError:
                snap = {}
            snap["promo_run_id"] = run.id
            op_run.input_json = json.dumps(snap, ensure_ascii=False)
            db.commit()

        self._log_promo(
            db,
            run.id,
            "run-start",
            f"评论推广任务已创建，{len(tags)} 个标签",
            payload_json=json.dumps({"tags": tags}, ensure_ascii=False),
        )

        thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(run.id,),
            daemon=True,
            name=f"promo-run-{run.id}",
        )
        thread.start()
        return run

    def retry_run(self, db: Session, run_id: int) -> PromoRun:
        old = self.get_run(db, run_id)
        if old is None:
            raise ValueError("Promo run not found")
        if old.status in PROMO_ACTIVE_STATUSES:
            raise ValueError("任务仍在进行中，无法重试")
        return self.start_run(db, old.variant_id)

    def abort_run(self, db: Session, run_id: int) -> PromoRun:
        run = self.get_run(db, run_id)
        if run is None:
            raise ValueError("Promo run not found")
        if run.status not in PROMO_ACTIVE_STATUSES:
            raise ValueError("任务未在运行，无法中止")
        run.status = "cancelling"
        db.commit()
        db.refresh(run)
        self._log_promo(db, run.id, "abort-requested", "正在中止任务…")
        adapter = self._active_adapters.get(run_id)
        if adapter is not None:
            threading.Thread(
                target=self._stop_adapter_sync,
                args=(adapter,),
                daemon=True,
                name=f"promo-abort-{run_id}",
            ).start()
        return run

    def list_logs(
        self,
        db: Session,
        run_id: int,
        *,
        since_id: int | None = None,
    ):
        return execution_log_service.list_logs(
            db,
            SUBJECT_PROMO_RUN,
            run_id,
            since_id=since_id,
        )

    def _finalize_operation(
        self,
        db: Session,
        *,
        operation_run_id: int | None,
        status: str,
        variant_id: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if not operation_run_id:
            return
        op = db.query(OperationRun).filter(OperationRun.id == operation_run_id).first()
        if op is None:
            return
        operation_service.finalize_run(
            db,
            op,
            status=status,
            variant_ids=[variant_id] if variant_id else None,
            error_message=error_message,
        )

    def _finish_cancelled(self, db: Session, run: PromoRun) -> None:
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        db.commit()
        self._log_promo(db, run.id, "cancelled", "任务已中止")
        self._finalize_operation(
            db,
            operation_run_id=run.operation_run_id,
            status="cancelled",
            variant_id=run.variant_id,
            error_message="任务已中止",
        )

    def _run_pipeline_thread(self, run_id: int) -> None:
        try:
            asyncio.run(self._run_pipeline(run_id))
        except Exception:
            logger.exception("Promo pipeline crashed for run %s", run_id)
            db = SessionLocal()
            try:
                run = db.query(PromoRun).filter(PromoRun.id == run_id).first()
                if run and run.status in PROMO_ACTIVE_STATUSES:
                    run.status = "failed"
                    run.error_message = "Internal pipeline error"
                    run.completed_at = datetime.utcnow()
                    db.commit()
                    self._log_promo(db, run.id, "failed", "内部错误导致任务失败")
                    self._finalize_operation(
                        db,
                        operation_run_id=run.operation_run_id,
                        status="failed",
                        variant_id=run.variant_id,
                        error_message="Internal pipeline error",
                    )
            finally:
                db.close()

    async def _run_pipeline(self, run_id: int) -> None:
        db = SessionLocal()
        try:
            run = db.query(PromoRun).filter(PromoRun.id == run_id).first()
            if run is None:
                return
            account = account_service.get(db, run.account_id)
            if account is None:
                run.status = "failed"
                run.error_message = "Account not found"
                run.completed_at = datetime.utcnow()
                db.commit()
                self._log_promo(db, run.id, "failed", "账号不存在")
                self._finalize_operation(
                    db,
                    operation_run_id=run.operation_run_id,
                    status="failed",
                    variant_id=run.variant_id,
                    error_message="Account not found",
                )
                return

            tags = json.loads(run.tags_json or "[]")
            run.status = "discovering"
            db.commit()
            on_step = execution_log_service.build_step_callback(db, SUBJECT_PROMO_RUN, run.id)
            self._log_promo(
                db,
                run.id,
                "discover-start",
                f"开始扫描 {len(tags)} 个标签",
                payload_json=json.dumps({"tags": tags}, ensure_ascii=False),
            )

            partial = False
            for tag in tags:
                db.refresh(run)
                if self._should_cancel(db, run_id):
                    self._finish_cancelled(db, run)
                    return

                self._log_promo(db, run.id, "discover-tag", f"扫描标签：{tag}")
                started = time.perf_counter()
                try:
                    items = await self._discover_for_tag(db, run, account, tag, on_step)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    added = 0
                    skipped = 0
                    for item in items:
                        if added >= PROMO_VIDEOS_PER_TAG:
                            break
                        if self._should_cancel(db, run_id):
                            self._finish_cancelled(db, run)
                            return

                        url = self._normalize_url(item["url"])
                        title = item.get("title")
                        if self._should_skip_url(
                            db,
                            account_id=run.account_id,
                            platform=run.platform,
                            url=url,
                        ):
                            skipped += 1
                            self._log_promo(
                                db,
                                run.id,
                                "url-skipped",
                                f"已跳过（曾扫描）：{title or url}",
                                payload_json=json.dumps(
                                    {"url": url, "title": title, "tag": tag},
                                    ensure_ascii=False,
                                ),
                            )
                            continue

                        self._upsert_seen_url(
                            db,
                            account_id=run.account_id,
                            platform=run.platform,
                            url=url,
                            promo_run_id=run.id,
                            status="seen",
                        )
                        db.add(
                            PromoTarget(
                                run_id=run.id,
                                tag=tag,
                                url=url,
                                title=title,
                                description=item.get("description"),
                                status="ok",
                            )
                        )
                        added += 1
                        self._log_promo(
                            db,
                            run.id,
                            "url-found",
                            f"收录：{title or url}",
                            payload_json=json.dumps(
                                {"url": url, "title": title, "tag": tag},
                                ensure_ascii=False,
                            ),
                        )
                    db.commit()
                    if added < PROMO_VIDEOS_PER_TAG:
                        partial = True
                    if run.operation_run_id:
                        operation_service.add_step(
                            db,
                            run_id=run.operation_run_id,
                            account_id=run.account_id,
                            platform=run.platform,
                            status="success",
                            attempt=1,
                            messages=[{"role": "user", "content": f"discover tag={tag}"}],
                            response_text=json.dumps(
                                {
                                    "tag": tag,
                                    "added": added,
                                    "skipped": skipped,
                                },
                                ensure_ascii=False,
                            ),
                            parsed={
                                "phase": "discover",
                                "tag": tag,
                                "added": added,
                                "skipped": skipped,
                            },
                            skill=None,
                            persona=None,
                            variant_id=run.variant_id,
                            duration_ms=duration_ms,
                        )
                except Exception as exc:
                    logger.warning("Discover failed for tag %s run %s: %s", tag, run_id, exc)
                    partial = True
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    db.add(
                        PromoTarget(
                            run_id=run.id,
                            tag=tag,
                            url="",
                            status="failed",
                            error_message=str(exc),
                        )
                    )
                    db.commit()
                    self._log_promo(
                        db,
                        run.id,
                        "discover-tag-failed",
                        f"标签 {tag} 扫描失败：{exc}",
                        status="failed",
                    )
                    if run.operation_run_id:
                        operation_service.add_step(
                            db,
                            run_id=run.operation_run_id,
                            account_id=run.account_id,
                            platform=run.platform,
                            status="failed",
                            attempt=1,
                            messages=[{"role": "user", "content": f"discover tag={tag}"}],
                            response_text=None,
                            parsed={"phase": "discover", "tag": tag},
                            skill=None,
                            persona=None,
                            variant_id=run.variant_id,
                            duration_ms=duration_ms,
                            error_message=str(exc),
                        )

            db.refresh(run)
            if self._should_cancel(db, run_id):
                self._finish_cancelled(db, run)
                return

            targets = (
                db.query(PromoTarget)
                .filter(PromoTarget.run_id == run.id, PromoTarget.status == "ok")
                .all()
            )
            self._log_promo(
                db,
                run.id,
                "discover-done",
                f"扫描完成，收录 {len(targets)} 条视频",
                payload_json=json.dumps({"target_count": len(targets)}, ensure_ascii=False),
            )
            if not targets:
                run.status = "failed"
                run.error_message = "未发现任何视频"
                run.completed_at = datetime.utcnow()
                db.commit()
                self._finalize_operation(
                    db,
                    operation_run_id=run.operation_run_id,
                    status="failed",
                    variant_id=run.variant_id,
                    error_message="未发现任何视频",
                )
                return

            run.status = "generating"
            db.commit()

            skill = account_service.resolve_skill(account, db)
            persona = account_service.resolve_persona(account, db) or ""
            skill_dict = skill.model_dump(exclude_none=True) if skill else {}

            for target in targets:
                db.refresh(run)
                if self._should_cancel(db, run_id):
                    self._finish_cancelled(db, run)
                    return

                self._log_promo(
                    db,
                    run.id,
                    "generate-start",
                    f"生成评论：{target.title or target.url}",
                    payload_json=json.dumps(
                        {"target_id": target.id, "url": target.url},
                        ensure_ascii=False,
                    ),
                )
                started = time.perf_counter()
                try:
                    comments, usage = self._generate_comments(
                        platform=run.platform,
                        tag=target.tag,
                        title=target.title or "",
                        description=target.description or "",
                        persona=persona,
                        skill_json=skill_dict,
                    )
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    for body in comments[:PROMO_COMMENTS_PER_VIDEO]:
                        db.add(
                            PromoComment(
                                run_id=run.id,
                                target_id=target.id,
                                body=body,
                                status="draft",
                                created_at=datetime.utcnow(),
                            )
                        )
                    if len(comments) < PROMO_COMMENTS_PER_VIDEO:
                        partial = True
                    self._mark_url_drafted(
                        db,
                        account_id=run.account_id,
                        platform=run.platform,
                        url=target.url,
                        promo_run_id=run.id,
                    )
                    db.commit()
                    self._log_promo(
                        db,
                        run.id,
                        "generate-done",
                        f"已生成 {min(len(comments), PROMO_COMMENTS_PER_VIDEO)} 条评论",
                        tool_name="llm_generate",
                        status="success",
                        duration_ms=duration_ms,
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        payload_json=json.dumps(
                            {
                                "target_id": target.id,
                                "url": target.url,
                                "comment_count": min(len(comments), PROMO_COMMENTS_PER_VIDEO),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    if run.operation_run_id:
                        messages = [
                            {
                                "role": "user",
                                "content": self._comment_prompt(
                                    platform=run.platform,
                                    tag=target.tag,
                                    title=target.title or "",
                                    description=target.description or "",
                                    persona=persona,
                                    skill_json=skill_dict,
                                ),
                            }
                        ]
                        operation_service.add_step(
                            db,
                            run_id=run.operation_run_id,
                            account_id=run.account_id,
                            platform=run.platform,
                            status="success",
                            attempt=1,
                            messages=messages,
                            response_text=json.dumps({"comments": comments}, ensure_ascii=False),
                            parsed={
                                "phase": "generate_comments",
                                "target_id": target.id,
                                "url": target.url,
                                "comments": comments[:PROMO_COMMENTS_PER_VIDEO],
                            },
                            skill=skill_dict,
                            persona=persona,
                            variant_id=run.variant_id,
                            model_id=usage.get("model_id"),
                            model_alias=usage.get("model_alias"),
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=usage.get("completion_tokens"),
                            total_tokens=usage.get("total_tokens"),
                            duration_ms=duration_ms,
                        )
                except Exception as exc:
                    logger.warning(
                        "Comment generation failed for target %s: %s", target.id, exc
                    )
                    partial = True
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    self._log_promo(
                        db,
                        run.id,
                        "generate-failed",
                        f"评论生成失败：{exc}",
                        tool_name="llm_generate",
                        status="failed",
                        duration_ms=duration_ms,
                        payload_json=json.dumps(
                            {"target_id": target.id, "url": target.url},
                            ensure_ascii=False,
                        ),
                    )
                    if run.operation_run_id:
                        operation_service.add_step(
                            db,
                            run_id=run.operation_run_id,
                            account_id=run.account_id,
                            platform=run.platform,
                            status="failed",
                            attempt=1,
                            messages=None,
                            response_text=None,
                            parsed={
                                "phase": "generate_comments",
                                "target_id": target.id,
                                "url": target.url,
                            },
                            skill=skill_dict,
                            persona=persona,
                            variant_id=run.variant_id,
                            duration_ms=duration_ms,
                            error_message=str(exc),
                        )

            run.status = "partial" if partial else "ready"
            run.completed_at = datetime.utcnow()
            db.commit()
            self._log_promo(
                db,
                run.id,
                "run-done",
                "任务完成" if run.status == "ready" else "任务部分完成",
            )
            self._finalize_operation(
                db,
                operation_run_id=run.operation_run_id,
                status="partial" if partial else "success",
                variant_id=run.variant_id,
            )
        finally:
            self._active_adapters.pop(run_id, None)
            db.close()

    async def _discover_for_tag(
        self,
        db: Session,
        run: PromoRun,
        account,
        tag: str,
        on_step,
    ) -> list[dict]:
        platform = get_platform(run.platform)
        if platform is None:
            raise ValueError(f"Unknown platform {run.platform}")

        template = self._load_prompt("promo_discover.md")
        prompt = template.format(
            platform_display=platform.display_name,
            platform=run.platform,
            home_url=platform.home_url,
            tag=tag,
            max_items=PROMO_VIDEOS_PER_TAG,
        )
        execution_dir = Path("data") / "promo_execution" / str(run.id) / tag.replace("/", "_")
        execution_dir.mkdir(parents=True, exist_ok=True)

        adapter = resolve_adapter_for_platform(run.platform)
        self._active_adapters[run.id] = adapter
        try:
            task = AgentTask(
                job_id=run.id,
                platform=run.platform,
                profile_path=account.browser_profile,
                prompt=prompt,
                execution_dir=str(execution_dir),
                metadata={"kind": "promo_discover", "tag": tag},
                on_step=on_step,
            )
            result = await adapter.execute(task)
            if result.status != AgentStatus.SUCCESS:
                raise ValueError(result.message or "Discovery agent failed")

            payload = self._parse_json_blob(result.message)
            items = payload.get("items") or []
            cleaned: list[dict] = []
            seen_urls: set[str] = set()
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                url = self._normalize_url(str(raw.get("url") or ""))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                cleaned.append(
                    {
                        "url": url,
                        "title": str(raw.get("title") or "").strip() or None,
                        "description": str(raw.get("description") or "").strip() or None,
                    }
                )
            return cleaned
        finally:
            self._active_adapters.pop(run.id, None)

    def _comment_prompt(
        self,
        *,
        platform: str,
        tag: str,
        title: str,
        description: str,
        persona: str,
        skill_json: dict,
    ) -> str:
        template = self._load_prompt("promo_comments.md")
        return template.format(
            platform=platform,
            title=title or "(无标题)",
            description=description or "(无描述)",
            tag=tag,
            persona=persona or "(默认)",
            skill_json=json.dumps(skill_json, ensure_ascii=False),
            count=PROMO_COMMENTS_PER_VIDEO,
        )

    def _generate_comments(
        self,
        *,
        platform: str,
        tag: str,
        title: str,
        description: str,
        persona: str,
        skill_json: dict,
    ) -> tuple[list[str], dict]:
        prompt = self._comment_prompt(
            platform=platform,
            tag=tag,
            title=title,
            description=description,
            persona=persona,
            skill_json=skill_json,
        )
        result = llm.chat_with_usage(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        payload = self._parse_json_blob(result.text)
        comments = payload.get("comments") or []
        cleaned = [str(c).strip() for c in comments if c and str(c).strip()]
        usage = {
            "model_id": result.model_id,
            "model_alias": result.model_alias,
            "prompt_tokens": result.usage.prompt_tokens if result.usage else None,
            "completion_tokens": result.usage.completion_tokens if result.usage else None,
            "total_tokens": result.usage.total_tokens if result.usage else None,
        }
        return cleaned, usage

    def get_run(self, db: Session, run_id: int) -> PromoRun | None:
        return db.query(PromoRun).filter(PromoRun.id == run_id).first()

    def list_runs_for_variant(self, db: Session, variant_id: int, limit: int = 20) -> list[PromoRun]:
        return (
            db.query(PromoRun)
            .filter(PromoRun.variant_id == variant_id)
            .order_by(PromoRun.id.desc())
            .limit(limit)
            .all()
        )

    def get_comment(self, db: Session, comment_id: int) -> PromoComment | None:
        return db.query(PromoComment).filter(PromoComment.id == comment_id).first()

    def update_comment(self, db: Session, comment_id: int, body: str) -> PromoComment:
        comment = self.get_comment(db, comment_id)
        if comment is None:
            raise ValueError("Comment not found")
        comment.body = body.strip()
        db.commit()
        db.refresh(comment)
        return comment

    def delete_comment(self, db: Session, comment_id: int) -> None:
        comment = self.get_comment(db, comment_id)
        if comment is None:
            raise ValueError("Comment not found")
        db.delete(comment)
        db.commit()


comment_promo_service = CommentPromoService()
