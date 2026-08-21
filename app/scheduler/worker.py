import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

from app.agent.base import AgentStatus, AgentTask
from app.agent.factory import create_agent_adapter
from app.config import settings
from app.constants import JobStatus, utcnow
from app.db.session import SessionLocal
from app.services.job_service import job_service


class SchedulerWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._adapter = create_agent_adapter()
        self._lock_fd: int | None = None

    def _lock_path(self) -> Path:
        return settings.data_dir / ".worker.lock"

    def _acquire_lock(self) -> bool:
        path = self._lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._lock_fd, str(os.getpid()).encode())
            return True
        except FileExistsError:
            return False

    def _release_lock(self) -> None:
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

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception:
                pass
            await asyncio.sleep(2)

    async def _tick(self) -> None:
        db = SessionLocal()
        try:
            self._recover_stale(db)
            self._promote_retry_jobs(db)
            jobs = job_service.claim_due_jobs(db)
            for job in jobs:
                await self._run_job(db, job)
        finally:
            db.close()

    def _recover_stale(self, db) -> None:
        from app.db.models import PublishJob

        cutoff = utcnow() - timedelta(minutes=10)
        rows = (
            db.query(PublishJob)
            .filter(PublishJob.status.in_([JobStatus.CLAIMED.value, JobStatus.EXECUTING.value]))
            .filter(PublishJob.started_at.isnot(None))
            .filter(PublishJob.started_at <= cutoff)
            .all()
        )
        for job in rows:
            job_service.mark_failed(db, job, "Stale job recovered")

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
        db.commit()

    async def _run_job(self, db, job) -> None:
        job.status = JobStatus.EXECUTING.value
        db.commit()

        prompt = job_service.build_task_prompt(db, job)
        execution_dir = job_service.execution_dir(job.id)
        task = AgentTask(
            job_id=job.id,
            platform=job.platform,
            profile_path=job.browser_profile,
            prompt=prompt,
            execution_dir=str(execution_dir),
        )

        job_service.add_log(db, job_id=job.id, step="start", message="Worker started job")
        result = await self._adapter.execute(task)

        for shot in result.screenshot_paths:
            job_service.add_log(
                db,
                job_id=job.id,
                step="screenshot",
                message=result.message,
                screenshot_path=shot,
            )

        if result.status == AgentStatus.SUCCESS:
            job.status = JobStatus.VERIFYING.value
            db.commit()
            job_service.finalize_success(db, job, {"message": result.message, "data": result.data})
            job_service.add_log(db, job_id=job.id, step="success", message=result.message)
        else:
            job_service.mark_failed(db, job, result.message)
            job_service.add_log(db, job_id=job.id, step="failed", message=result.message)


worker = SchedulerWorker()
