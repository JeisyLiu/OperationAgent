import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import JobStatus, RETRY_BACKOFF_SECONDS, utcnow
from app.db.models import ExecutionLog, PublishJob
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
                f"Platform '{variant.platform}' does not support publishing yet. "
                "You can create an account and log in, but scheduling jobs is not available."
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
        if job.status in {JobStatus.SUCCESS.value, JobStatus.DEAD.value, JobStatus.CANCELLED.value}:
            raise ValueError("Job cannot be cancelled in current status")
        job.status = JobStatus.CANCELLED.value
        job.completed_at = utcnow()
        db.commit()
        db.refresh(job)
        return job

    def retry(self, db: Session, job: PublishJob) -> PublishJob:
        job.status = JobStatus.PENDING.value
        job.scheduled_at = utcnow()
        job.error_message = None
        db.commit()
        db.refresh(job)
        return job

    def get_logs(self, db: Session, job_id: int) -> list[ExecutionLog]:
        return (
            db.query(ExecutionLog)
            .filter(ExecutionLog.job_id == job_id)
            .order_by(ExecutionLog.id.asc())
            .all()
        )

    def add_log(
        self,
        db: Session,
        *,
        job_id: int,
        step: str,
        message: str | None = None,
        screenshot_path: str | None = None,
    ) -> ExecutionLog:
        log = ExecutionLog(
            job_id=job_id,
            step=step,
            message=message,
            screenshot_path=screenshot_path,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

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
        if variant and variant.hashtags_json:
            hashtags = json.loads(variant.hashtags_json)
        media_path = variant.media_path if variant else ""
        return template.format(
            platform=job.platform,
            media_path=media_path,
            title=variant.title if variant else "",
            caption=variant.caption if variant else "",
            hashtags=", ".join(hashtags),
        )


job_service = JobService()
