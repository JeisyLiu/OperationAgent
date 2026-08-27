from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import OperationRun, PublishJob
from app.db.session import get_db
from app.schemas.history import (
    HistoryItemResponse,
    HistoryListResponse,
    OperationRunResponse,
    operation_run_to_response,
)
from app.services.operation_service import operation_service

router = APIRouter(prefix="/api", tags=["history"])

_KIND_LABELS = {
    "generate": "生成内容包",
    "rewrite": "LLM 重写内容包",
    "promo": "评论推广",
    "publish": "推送任务",
}


def _operation_title(run: OperationRun) -> str:
    label = _KIND_LABELS.get(run.kind, run.kind)
    account_ids = []
    if run.account_ids_json:
        import json

        try:
            account_ids = json.loads(run.account_ids_json)
        except json.JSONDecodeError:
            pass
    count = len(account_ids)
    if run.kind == "rewrite":
        return f"{label}"
    if run.kind == "promo":
        return run.summary or label
    if count:
        return f"{label} · {count} 账号"
    return label


def _job_title(job: PublishJob) -> str:
    return f"{_KIND_LABELS['publish']} #{job.id} · {job.platform}"


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> HistoryListResponse:
    items: list[HistoryItemResponse] = []

    if kind is None or kind in ("generate", "rewrite", "promo"):
        op_query = db.query(OperationRun)
        if kind in ("generate", "rewrite", "promo"):
            op_query = op_query.filter(OperationRun.kind == kind)
        for run in op_query.all():
            items.append(
                HistoryItemResponse(
                    id=f"op-{run.id}",
                    source="operation",
                    kind=run.kind,
                    title=_operation_title(run),
                    status=run.status,
                    total_tokens=run.total_tokens,
                    created_at=run.created_at or datetime.utcnow(),
                    ref_id=run.id,
                )
            )

    if kind is None or kind == "publish":
        for job in db.query(PublishJob).all():
            items.append(
                HistoryItemResponse(
                    id=f"job-{job.id}",
                    source="job",
                    kind="publish",
                    title=_job_title(job),
                    status=job.status,
                    total_tokens=None,
                    created_at=job.created_at or datetime.utcnow(),
                    ref_id=job.id,
                )
            )

    items.sort(key=lambda x: x.created_at, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]
    return HistoryListResponse(items=page, total=total, limit=limit, offset=offset)


@router.get("/operations/{run_id}", response_model=OperationRunResponse)
def get_operation(run_id: int, db: Session = Depends(get_db)) -> OperationRunResponse:
    import json

    from app.db.models import PromoRun
    from app.services.execution_log_service import SUBJECT_PROMO_RUN, execution_log_service

    run = operation_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    steps = operation_service.get_steps(db, run_id)

    execution_logs = []
    promo_run_id = None
    if run.kind == "promo":
        if run.input_json:
            try:
                snap = json.loads(run.input_json)
                raw = snap.get("promo_run_id")
                promo_run_id = int(raw) if raw is not None else None
            except (json.JSONDecodeError, TypeError, ValueError):
                promo_run_id = None
        if promo_run_id is None:
            promo = (
                db.query(PromoRun)
                .filter(PromoRun.operation_run_id == run.id)
                .order_by(PromoRun.id.desc())
                .first()
            )
            if promo:
                promo_run_id = promo.id
        if promo_run_id is not None:
            execution_logs = execution_log_service.list_logs(
                db, SUBJECT_PROMO_RUN, promo_run_id
            )

    return operation_run_to_response(
        run,
        steps,
        execution_logs=execution_logs,
        promo_run_id=promo_run_id,
    )
