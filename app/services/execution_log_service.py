import json
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.agent.base import StepEvent
from app.db.models import ExecutionLog

SUBJECT_JOB = "job"
SUBJECT_PROMO_RUN = "promo_run"


class ExecutionLogService:
    def add_log(
        self,
        db: Session,
        *,
        subject_type: str,
        subject_id: int,
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
        job_id = subject_id if subject_type == SUBJECT_JOB else None
        log = ExecutionLog(
            job_id=job_id,
            subject_type=subject_type,
            subject_id=subject_id,
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
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def add_step_event(
        self,
        db: Session,
        *,
        subject_type: str,
        subject_id: int,
        event: StepEvent,
    ) -> ExecutionLog:
        payload = dict(event.payload or {})
        payload["phase"] = event.phase
        return self.add_log(
            db,
            subject_type=subject_type,
            subject_id=subject_id,
            step=f"{event.phase}-{event.step}",
            message=event.message,
            screenshot_path=event.screenshot_path,
            tool_name=event.tool_name,
            status=event.status,
            duration_ms=event.duration_ms,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            total_tokens=event.total_tokens,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )

    def build_step_callback(self, db: Session, subject_type: str, subject_id: int) -> Callable[[StepEvent], None]:
        def on_step(event: StepEvent) -> None:
            self.add_step_event(
                db,
                subject_type=subject_type,
                subject_id=subject_id,
                event=event,
            )

        return on_step

    def list_logs(
        self,
        db: Session,
        subject_type: str,
        subject_id: int,
        *,
        since_id: int | None = None,
    ) -> list[ExecutionLog]:
        query = (
            db.query(ExecutionLog)
            .filter(
                ExecutionLog.subject_type == subject_type,
                ExecutionLog.subject_id == subject_id,
            )
            .order_by(ExecutionLog.id.asc())
        )
        if since_id is not None:
            query = query.filter(ExecutionLog.id > since_id)
        return query.all()

    def get_logs_for_job(self, db: Session, job_id: int) -> list[ExecutionLog]:
        return self.list_logs(db, SUBJECT_JOB, job_id)


execution_log_service = ExecutionLogService()
