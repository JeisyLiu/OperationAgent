import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.base import StepEvent
from app.config import settings
from app.constants import (
    FailureCode,
    JobStatus,
    REPUBLISH_ALLOWED_STATUSES,
    RETRY_ALLOWED_STATUSES,
    RETRY_BACKOFF_SECONDS,
    RUNNING_JOB_STATUSES,
    StepStatus,
    utcnow,
)
from app.db.models import ExecutionLog, PublishJob
from app.services.execution_log_service import SUBJECT_JOB, execution_log_service
from app.platforms import is_publishable, require_platform
from app.services.account_service import account_service
from app.services.content_service import content_service


class JobService:
    def list_jobs(self, db: Session, status: str | None = None) -> list[PublishJob]:
        query = db.query(PublishJob).order_by(PublishJob.id.desc())
        if status:
            query = query.filter(PublishJob.status == status)
        return query.all()

    def get(self, db: Session, job_id: int) -> PublishJob | None:
        return db.query(PublishJob).filter(PublishJob.id == job_id).first()

    def create(
        self,
        db: Session,
        *,
        content_variant_id: int,
        account_id: int,
        scheduled_at: datetime,
        max_retries: int = 3,
    ) -> PublishJob:
        variant = content_service.get_variant(db, content_variant_id)
        if variant is None:
            raise ValueError("Variant not found")
        account = account_service.get(db, account_id)
        if account is None:
            raise ValueError("Account not found")
        if account.status != "ACTIVE":
            raise ValueError("Account must be ACTIVE before scheduling jobs")
        if account.platform != variant.platform:
            raise ValueError(
                f"Account platform '{account.platform}' does not match variant platform '{variant.platform}'"
            )

        try:
            require_platform(variant.platform)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        if not is_publishable(variant.platform):
            raise ValueError(
                f"Platform '{variant.platform}' is disabled and cannot accept publish jobs."
            )

        job = PublishJob(
            content_variant_id=content_variant_id,
            account_id=account_id,
            platform=variant.platform,
            browser_profile=account.browser_profile,
            scheduled_at=scheduled_at,
            status=JobStatus.PENDING.value,
            max_retries=max_retries,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def create_bulk(
        self,
        db: Session,
        items: list[dict],
    ) -> tuple[list[PublishJob], list[dict]]:
        created: list[PublishJob] = []
        failed: list[dict] = []
        for item in items:
            variant_id = item["content_variant_id"]
            account_id = item["account_id"]
            scheduled_at = item.get("scheduled_at") or utcnow()
            max_retries = item.get("max_retries", 3)
            try:
                job = self.create(
                    db,
                    content_variant_id=variant_id,
                    account_id=account_id,
                    scheduled_at=scheduled_at,
                    max_retries=max_retries,
                )
                created.append(job)
            except ValueError as exc:
                failed.append(
                    {
                        "content_variant_id": variant_id,
                        "account_id": account_id,
                        "detail": str(exc),
                    }
                )
        return created, failed

    def cancel(self, db: Session, job: PublishJob) -> PublishJob:
        if job.status in {
            JobStatus.SUCCESS.value,
            JobStatus.DEAD.value,
            JobStatus.CANCELLED.value,
        }:
            raise ValueError("Job cannot be cancelled in current status")
        job.status = JobStatus.CANCELLED.value
        job.completed_at = utcnow()
        db.commit()
        db.refresh(job)
        return job

    def resume_from_human(self, db: Session, job: PublishJob) -> PublishJob:
        if job.status != JobStatus.WAITING_HUMAN.value:
            raise ValueError("Job is not waiting for human intervention")
        job.status = JobStatus.PENDING.value
        job.error_message = None
        job.scheduled_at = utcnow()
        job.completed_at = None
        db.commit()
        self.add_log(
            db,
            job_id=job.id,
            step="resume",
            message="User resumed after human intervention",
            status=StepStatus.SUCCESS.value,
        )
        db.refresh(job)
        return job

    def mark_waiting_human(
        self,
        db: Session,
        job: PublishJob,
        message: str,
        *,
        error_code: str,
        action_url: str | None = None,
        guidance: str | None = None,
    ) -> PublishJob:
        payload = {
            "message": message,
            "error_code": error_code,
            "action_url": action_url,
            "guidance": guidance,
        }
        job.status = JobStatus.WAITING_HUMAN.value
        job.error_message = message
        job.result_json = json.dumps(payload)
        job.completed_at = utcnow()
        db.commit()
        db.refresh(job)
        return job

    def retry(self, db: Session, job: PublishJob) -> PublishJob:
        if job.status not in RETRY_ALLOWED_STATUSES:
            raise ValueError(
                f"Job cannot be retried in status {job.status}. "
                "Use republish for SUCCESS or resume for WAITING_HUMAN."
            )
        job.status = JobStatus.PENDING.value
        job.scheduled_at = utcnow()
        job.error_message = None
        job.retry_count = 0
        job.completed_at = None
        db.commit()
        self.add_log(
            db,
            job_id=job.id,
            step="retry",
            message="User retried job with original content",
            status=StepStatus.SUCCESS.value,
            tool_name="user",
        )
        db.refresh(job)
        return job

    def _ensure_republishable(self, job: PublishJob) -> None:
        if job.status in RUNNING_JOB_STATUSES:
            raise ValueError(f"Job cannot be republished while {job.status}")
        if job.status not in REPUBLISH_ALLOWED_STATUSES:
            raise ValueError(f"Job cannot be republished in status {job.status}")

    def _build_republish_preview(
        self,
        db: Session,
        job: PublishJob,
        *,
        rewrite: bool,
    ) -> dict:
        from app.agent.factory import adapter_name_for_platform
        from app.services.llm_model_service import llm_model_service

        self._ensure_republishable(job)
        adapter = adapter_name_for_platform(job.platform)
        will_call_execution_llm = adapter != "mock"
        enabled = llm_model_service.list_enabled_configs(db)
        llm_items = [
            {
                "alias": cfg.alias,
                "provider": cfg.provider,
                "model": cfg.model,
                "base_url": cfg.base_url,
            }
            for cfg in enabled
        ]
        warnings: list[str] = []
        if job.status == JobStatus.SUCCESS.value:
            warnings.append("原任务已成功发布，再发可能产生重复内容")
        if rewrite and not enabled:
            warnings.append("未配置启用的 LLM，重写后再发将失败")
        return {
            "will_call_content_llm": rewrite,
            "will_call_execution_llm": will_call_execution_llm,
            "llm": llm_items,
            "adapter": adapter,
            "platform": job.platform,
            "account_id": job.account_id,
            "source_status": job.status,
            "variant_mode": "clone_variant" if rewrite else "reuse_variant",
            "warnings": warnings,
        }

    def preview_republish(
        self,
        db: Session,
        job: PublishJob,
        *,
        rewrite: bool = False,
    ) -> dict:
        return self._build_republish_preview(db, job, rewrite=rewrite)

    def republish(
        self,
        db: Session,
        job: PublishJob,
        *,
        rewrite: bool = False,
        scheduled_at: datetime | None = None,
        max_retries: int = 3,
    ) -> dict:
        from app.services.content_generate_service import content_generate_service

        self._ensure_republishable(job)
        variant = content_service.get_variant(db, job.content_variant_id)
        if variant is None:
            raise ValueError("Content variant not found")

        target_variant_id = job.content_variant_id
        rewritten = False

        if rewrite:
            result = content_generate_service.generate_for_accounts(
                db,
                asset_id=variant.asset_id,
                account_ids=[job.account_id],
                replace_drafts=False,
            )
            if result.errors:
                detail = result.errors[0].detail
                raise ValueError(f"Failed to rewrite content: {detail}")
            if not result.variants:
                raise ValueError("Failed to rewrite content: no variant created")
            generated = result.variants[0]
            new_variant = content_service.get_variant(db, generated.id)
            if new_variant is None:
                raise ValueError("Failed to rewrite content: variant missing after generation")
            content_service.update_variant(
                db,
                new_variant,
                status="READY",
            )
            target_variant_id = new_variant.id
            rewritten = True

        when = scheduled_at or utcnow()
        new_job = self.create(
            db,
            content_variant_id=target_variant_id,
            account_id=job.account_id,
            scheduled_at=when,
            max_retries=max_retries,
        )

        self.add_log(
            db,
            job_id=job.id,
            step="republished_as",
            message=f"Republished as job #{new_job.id}",
            status=StepStatus.SUCCESS.value,
            tool_name="user",
            payload_json=json.dumps(
                {
                    "new_job_id": new_job.id,
                    "rewrite": rewrite,
                    "variant_id": target_variant_id,
                },
                ensure_ascii=False,
            ),
        )
        self.add_log(
            db,
            job_id=new_job.id,
            step="republish_from",
            message=f"Republish from job #{job.id}",
            status=StepStatus.SUCCESS.value,
            tool_name="user",
            payload_json=json.dumps(
                {
                    "source_job_id": job.id,
                    "rewrite": rewrite,
                    "variant_id": target_variant_id,
                },
                ensure_ascii=False,
            ),
        )

        return {
            "original_job": job,
            "new_job": new_job,
            "variant_id": target_variant_id,
            "rewritten": rewritten,
        }

    def get_logs(self, db: Session, job_id: int) -> list[ExecutionLog]:
        return execution_log_service.get_logs_for_job(db, job_id)

    def add_log(
        self,
        db: Session,
        *,
        job_id: int,
        step: str,
        message: str | None = None,
        screenshot_path: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        payload_json: str | None = None,
        started_at: datetime | None = None,
    ) -> ExecutionLog:
        return execution_log_service.add_log(
            db,
            subject_type=SUBJECT_JOB,
            subject_id=job_id,
            step=step,
            message=message,
            screenshot_path=screenshot_path,
            tool_name=tool_name,
            status=status,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            payload_json=payload_json,
            started_at=started_at,
        )

    def add_step_event(self, db: Session, *, job_id: int, event: StepEvent) -> ExecutionLog:
        return execution_log_service.add_step_event(
            db,
            subject_type=SUBJECT_JOB,
            subject_id=job_id,
            event=event,
        )

    def build_step_callback(self, db: Session, job_id: int):
        return execution_log_service.build_step_callback(db, SUBJECT_JOB, job_id)

    def get_job_detail(self, db: Session, job_id: int) -> dict | None:
        job = self.get(db, job_id)
        if job is None:
            return None
        steps = self.get_logs(db, job_id)
        total_duration = sum(s.duration_ms or 0 for s in steps)
        prompt_values = [s.prompt_tokens for s in steps if s.prompt_tokens is not None]
        completion_values = [s.completion_tokens for s in steps if s.completion_tokens is not None]
        total_values = [s.total_tokens for s in steps if s.total_tokens is not None]
        totals = {
            "duration_ms": total_duration,
            "prompt_tokens": sum(prompt_values) if prompt_values else None,
            "completion_tokens": sum(completion_values) if completion_values else None,
            "total_tokens": sum(total_values) if total_values else None,
        }
        return {
            "job": job,
            "steps": steps,
            "totals": totals,
            "account_id": job.account_id,
        }

    def execution_dir(self, job_id: int) -> Path:
        path = settings.data_dir / "execution" / str(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def claim_due_jobs(self, db: Session, limit: int = 5) -> list[PublishJob]:
        now = utcnow()
        due = (
            db.query(PublishJob)
            .filter(PublishJob.status == JobStatus.PENDING.value)
            .filter(PublishJob.scheduled_at <= now)
            .order_by(PublishJob.scheduled_at.asc())
            .limit(limit)
            .all()
        )
        claimed: list[PublishJob] = []
        for job in due:
            updated = (
                db.query(PublishJob)
                .filter(PublishJob.id == job.id, PublishJob.status == JobStatus.PENDING.value)
                .update(
                    {
                        PublishJob.status: JobStatus.CLAIMED.value,
                        PublishJob.started_at: utcnow(),
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if updated:
                fresh = db.query(PublishJob).filter(PublishJob.id == job.id).first()
                if fresh is not None:
                    claimed.append(fresh)
        return claimed

    def mark_failed(
        self,
        db: Session,
        job: PublishJob,
        message: str,
        *,
        error_code: str | None = None,
    ) -> PublishJob:
        from app.constants import NON_RETRYABLE_FAILURES

        job.error_message = message
        payload = {"message": message}
        if error_code:
            payload["error_code"] = error_code
        job.result_json = json.dumps(payload)

        if error_code in NON_RETRYABLE_FAILURES:
            job.status = JobStatus.FAILED.value
            job.completed_at = utcnow()
        else:
            job.retry_count += 1
            if job.retry_count >= job.max_retries:
                job.status = JobStatus.DEAD.value
                job.completed_at = utcnow()
            else:
                job.status = JobStatus.RETRY.value
                backoff_idx = min(job.retry_count - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                job.scheduled_at = utcnow() + timedelta(seconds=RETRY_BACKOFF_SECONDS[backoff_idx])
        db.commit()
        db.refresh(job)
        return job

    def recover_stale_jobs(self, db: Session, *, minutes: int = 10) -> int:
        cutoff = utcnow() - timedelta(minutes=minutes)
        rows = (
            db.query(PublishJob)
            .filter(PublishJob.status.in_([JobStatus.CLAIMED.value, JobStatus.EXECUTING.value]))
            .filter(PublishJob.started_at.isnot(None))
            .filter(PublishJob.started_at <= cutoff)
            .all()
        )
        for job in rows:
            job.status = JobStatus.RETRY.value
            job.error_message = "Stale job recovered after worker timeout"
            job.scheduled_at = utcnow()
        if rows:
            db.commit()
        return len(rows)

    def finalize_success(self, db: Session, job: PublishJob, result: dict) -> PublishJob:
        job.status = JobStatus.SUCCESS.value
        job.result_json = json.dumps(result)
        job.completed_at = utcnow()
        db.commit()
        db.refresh(job)
        return job

    def build_task_prompt(self, db: Session, job: PublishJob) -> str:
        variant = content_service.get_variant(db, job.content_variant_id)
        template_path = Path(__file__).resolve().parents[1] / "prompts" / "publish_task.md"
        template = template_path.read_text(encoding="utf-8")
        hashtags = []
        section = ""
        if variant and variant.hashtags_json:
            hashtags = json.loads(variant.hashtags_json)
        if variant and variant.extra_json:
            try:
                extra = json.loads(variant.extra_json)
                section = extra.get("section") or ""
            except json.JSONDecodeError:
                section = ""
        media_path = variant.media_path if variant else ""
        if not media_path:
            media_path = "(none — text/image post, no video file)"

        from app.platforms import get_platform

        platform = get_platform(job.platform)
        home_url = platform.home_url if platform else ""
        upload_url = platform.upload_url if platform else home_url

        return template.format(
            platform=job.platform,
            home_url=home_url,
            upload_url=upload_url,
            media_path=media_path,
            title=variant.title if variant else "",
            caption=variant.caption if variant else "",
            hashtags=", ".join(hashtags),
            section=section or "(none)",
        )


job_service = JobService()
