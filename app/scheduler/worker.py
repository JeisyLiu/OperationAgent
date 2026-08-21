import asyncio
import logging
from datetime import timedelta

from app.agent.base import AgentStatus
from app.agent.factory import create_agent_adapter
from app.channels.base import PublishContext
from app.channels.registry import get_channel
from app.config import settings
from app.constants import JobStatus, utcnow
from app.db.session import SessionLocal
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service

logger = logging.getLogger(__name__)


class SchedulerWorker:
    STALE_JOB_MINUTES = 10

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._adapter = create_agent_adapter()
        self._lock_fd: int | None = None
        self._current_job_id: int | None = None
        self._lock_warning_logged = False

    @property
    def current_job_id(self) -> int | None:
        return self._current_job_id

    @property
    def adapter(self):
        return self._adapter

    def _lock_path(self):
        return settings.data_dir / ".worker.lock"

    def _acquire_lock(self) -> bool:
        import os
        from pathlib import Path

        path = self._lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._lock_fd, str(os.getpid()).encode())
            self._lock_warning_logged = False
            return True
        except FileExistsError:
            if not self._lock_warning_logged:
                logger.warning("Worker lock already held; another worker may be running")
                self._lock_warning_logged = True
            return False

    def _release_lock(self) -> None:
        import os
        from pathlib import Path

        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        lock_path = self._lock_path()
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

    async def start(self) -> None:
        if self._running:
            return
        if not self._acquire_lock():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler worker started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._adapter.stop()
        self._release_lock()
        logger.info("Scheduler worker stopped")

    async def pause_current(self) -> None:
        await self._adapter.pause()

    async def stop_current(self) -> None:
        await self._adapter.stop()

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "lock_held": self._lock_fd is not None,
            "current_job_id": self._current_job_id,
            "adapter_status": self._adapter.get_status().value,
        }

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Worker tick failed")
            await asyncio.sleep(2)

    async def _tick(self) -> None:
        db = SessionLocal()
        try:
            recovered = job_service.recover_stale_jobs(db, minutes=self.STALE_JOB_MINUTES)
            if recovered:
                logger.warning("Recovered %s stale job(s)", recovered)
            self._promote_retry_jobs(db)
            jobs = job_service.claim_due_jobs(db)
            for job in jobs:
                await self._run_job(db, job)
        finally:
            db.close()

    def _promote_retry_jobs(self, db) -> None:
        from app.db.models import PublishJob

        now = utcnow()
        rows = (
            db.query(PublishJob)
            .filter(PublishJob.status == JobStatus.RETRY.value)
            .filter(PublishJob.scheduled_at <= now)
            .all()
        )
        for job in rows:
            job.status = JobStatus.PENDING.value
        if rows:
            db.commit()

    async def _run_job(self, db, job) -> None:
        self._current_job_id = job.id
        try:
            job.status = JobStatus.EXECUTING.value
            db.commit()

            account = account_service.get(db, job.account_id)
            variant = content_service.get_variant(db, job.content_variant_id)
            if account is None or variant is None:
                job_service.mark_failed(db, job, "Missing account or variant")
                return

            prompt = job_service.build_task_prompt(db, job)
            execution_dir = job_service.execution_dir(job.id)
            channel = get_channel(job.platform)
            ctx = PublishContext(
                db=db,
                job=job,
                account=account,
                variant=variant,
                adapter=self._adapter,
                execution_dir=execution_dir,
                prompt=prompt,
            )

            job_service.add_log(db, job_id=job.id, step="start", message="Worker started job via channel")
            result = await channel.publish(ctx)

            for shot in result.screenshot_paths:
                job_service.add_log(
                    db,
                    job_id=job.id,
                    step="screenshot",
                    message=result.message,
                    screenshot_path=shot,
                )

            if result.success:
                job.status = JobStatus.VERIFYING.value
                db.commit()
                job_service.finalize_success(db, job, result.data or {"message": result.message})
                job_service.add_log(db, job_id=job.id, step="success", message=result.message)
            else:
                job_service.mark_failed(db, job, result.message, error_code=result.error_code)
                job_service.add_log(db, job_id=job.id, step="failed", message=result.message)
        finally:
            self._current_job_id = None


worker = SchedulerWorker()
