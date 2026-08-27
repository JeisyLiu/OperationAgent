import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import PromoComment, PromoTarget
from app.db.session import get_db
from app.schemas.jobs import ExecutionLogResponse
from app.schemas.promo import (
    PromoCommentResponse,
    PromoCommentUpdate,
    PromoRunCreate,
    PromoRunListResponse,
    PromoRunResponse,
    PromoTargetResponse,
)
from app.services.comment_promo_service import comment_promo_service

router = APIRouter(prefix="/api/promo", tags=["promo"])


def _run_to_response(
    db: Session,
    run,
    *,
    since_id: int | None = None,
) -> PromoRunResponse:
    tags = json.loads(run.tags_json or "[]")
    targets = (
        db.query(PromoTarget)
        .filter(PromoTarget.run_id == run.id)
        .order_by(PromoTarget.id.asc())
        .all()
    )
    comments = (
        db.query(PromoComment)
        .filter(PromoComment.run_id == run.id)
        .order_by(PromoComment.id.asc())
        .all()
    )
    by_target: dict[int, list[PromoCommentResponse]] = {}
    for comment in comments:
        by_target.setdefault(comment.target_id, []).append(
            PromoCommentResponse.model_validate(comment)
        )

    target_responses = []
    for target in targets:
        if target.status == "failed" and not target.url:
            continue
        target_responses.append(
            PromoTargetResponse(
                id=target.id,
                run_id=target.run_id,
                tag=target.tag,
                url=target.url,
                title=target.title,
                description=target.description,
                status=target.status,
                error_message=target.error_message,
                comments=by_target.get(target.id, []),
            )
        )

    logs = comment_promo_service.list_logs(db, run.id, since_id=since_id)

    return PromoRunResponse(
        id=run.id,
        variant_id=run.variant_id,
        asset_id=run.asset_id,
        account_id=run.account_id,
        platform=run.platform,
        status=run.status,
        tags=tags,
        operation_run_id=run.operation_run_id,
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
        targets=target_responses,
        logs=[ExecutionLogResponse.model_validate(log) for log in logs],
    )


@router.post("/runs", response_model=PromoRunResponse)
def create_promo_run(payload: PromoRunCreate, db: Session = Depends(get_db)) -> PromoRunResponse:
    try:
        run = comment_promo_service.start_run(db, payload.variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_to_response(db, run)


@router.get("/runs", response_model=PromoRunListResponse)
def list_promo_runs(
    variant_id: int = Query(..., ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PromoRunListResponse:
    runs = comment_promo_service.list_runs_for_variant(db, variant_id, limit=limit)
    items = [_run_to_response(db, run) for run in runs]
    return PromoRunListResponse(items=items, total=len(items))


@router.get("/runs/{run_id}", response_model=PromoRunResponse)
def get_promo_run(
    run_id: int,
    since_id: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> PromoRunResponse:
    run = comment_promo_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Promo run not found")
    return _run_to_response(db, run, since_id=since_id)


@router.post("/runs/{run_id}/abort", response_model=PromoRunResponse)
def abort_promo_run(run_id: int, db: Session = Depends(get_db)) -> PromoRunResponse:
    try:
        run = comment_promo_service.abort_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_to_response(db, run)


@router.post("/runs/{run_id}/retry", response_model=PromoRunResponse)
def retry_promo_run(run_id: int, db: Session = Depends(get_db)) -> PromoRunResponse:
    try:
        run = comment_promo_service.retry_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_to_response(db, run)


@router.patch("/comments/{comment_id}", response_model=PromoCommentResponse)
def update_promo_comment(
    comment_id: int,
    payload: PromoCommentUpdate,
    db: Session = Depends(get_db),
) -> PromoCommentResponse:
    try:
        comment = comment_promo_service.update_comment(db, comment_id, payload.body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromoCommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}")
def delete_promo_comment(comment_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        comment_promo_service.delete_comment(db, comment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
