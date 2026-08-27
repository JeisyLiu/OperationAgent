import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import OperationRun, OperationStep


def _sum_tokens(steps: list[OperationStep]) -> tuple[int | None, int | None, int | None]:
    prompt = completion = total = 0
    has_any = False
    for step in steps:
        if step.prompt_tokens is not None:
            prompt += step.prompt_tokens
            has_any = True
        if step.completion_tokens is not None:
            completion += step.completion_tokens
            has_any = True
        if step.total_tokens is not None:
            total += step.total_tokens
            has_any = True
    if not has_any:
        return None, None, None
    return prompt, completion, total


class OperationService:
    def create_run(
        self,
        db: Session,
        *,
        kind: str,
        asset_id: int | None,
        account_ids: list[int],
        summary: str,
        input_snapshot: dict[str, Any] | None = None,
    ) -> OperationRun:
        run = OperationRun(
            kind=kind,
            status="running",
            asset_id=asset_id,
            account_ids_json=json.dumps(account_ids, ensure_ascii=False),
            variant_ids_json=json.dumps([], ensure_ascii=False),
            input_json=json.dumps(input_snapshot or {}, ensure_ascii=False),
            summary=summary,
            created_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def add_step(
        self,
        db: Session,
        *,
        run_id: int,
        account_id: int | None,
        platform: str | None,
        status: str,
        attempt: int,
        messages: list[dict[str, str]] | None,
        response_text: str | None,
        parsed: dict[str, Any] | None,
        skill: dict[str, Any] | None,
        persona: str | None,
        model_id: int | None = None,
        model_alias: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        duration_ms: int | None = None,
        variant_id: int | None = None,
        error_message: str | None = None,
    ) -> OperationStep:
        step = OperationStep(
            run_id=run_id,
            account_id=account_id,
            platform=platform,
            variant_id=variant_id,
            status=status,
            attempt=attempt,
            model_id=model_id,
            model_alias=model_alias,
            skill_json=json.dumps(skill or {}, ensure_ascii=False),
            persona=persona,
            messages_json=json.dumps(messages or [], ensure_ascii=False),
            response_text=response_text,
            parsed_json=json.dumps(parsed or {}, ensure_ascii=False) if parsed is not None else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            error_message=error_message,
            created_at=datetime.utcnow(),
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        return step

    def finalize_run(
        self,
        db: Session,
        run: OperationRun,
        *,
        status: str,
        variant_ids: list[int] | None = None,
        error_message: str | None = None,
    ) -> OperationRun:
        steps = (
            db.query(OperationStep).filter(OperationStep.run_id == run.id).all()
        )
        prompt, completion, total = _sum_tokens(steps)
        run.status = status
        run.variant_ids_json = json.dumps(variant_ids or [], ensure_ascii=False)
        run.prompt_tokens = prompt
        run.completion_tokens = completion
        run.total_tokens = total
        run.error_message = error_message
        run.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run

    def get_run(self, db: Session, run_id: int) -> OperationRun | None:
        return db.query(OperationRun).filter(OperationRun.id == run_id).first()

    def get_steps(self, db: Session, run_id: int) -> list[OperationStep]:
        return (
            db.query(OperationStep)
            .filter(OperationStep.run_id == run_id)
            .order_by(OperationStep.id.asc())
            .all()
        )


operation_service = OperationService()
