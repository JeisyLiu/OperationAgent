from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.constants import utcnow
from app.db.session import get_db
from app.schemas.jobs import (
    BulkJobCreate,
    BulkJobResponse,
    BulkJobResultItem,
    ExecutionLogResponse,
    JobCreate,
    JobDetailResponse,
    JobDetailTotals,
    JobResponse,
    RepublishPreviewResponse,
    RepublishRequest,
    RepublishResponse,
)
from app.services.job_service import job_service
from app.services.event_bus import emit_job_updated, emit_readiness_changed

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _emit_job(job) -> None:
    emit_job_updated(job.id, job.status)


@router.get("", response_model=list[JobResponse])
def list_jobs(status: str | None = None, db: Session = Depends(get_db)) -> list[JobResponse]:
    return job_service.list_jobs(db, status=status)


@router.post("", response_model=JobResponse)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> JobResponse:
    scheduled_at = payload.scheduled_at or utcnow()
    try:
        job = job_service.create(
            db,
            content_variant_id=payload.content_variant_id,
            account_id=payload.account_id,
            scheduled_at=scheduled_at,
            max_retries=payload.max_retries,
        )
        _emit_job(job)
        return job
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bulk", response_model=BulkJobResponse)
def create_jobs_bulk(payload: BulkJobCreate, db: Session = Depends(get_db)) -> BulkJobResponse:
    items = [
        {
            "content_variant_id": item.content_variant_id,
            "account_id": item.account_id,
            "scheduled_at": item.scheduled_at or utcnow(),
            "max_retries": item.max_retries,
        }
        for item in payload.items
    ]
    created, failed = job_service.create_bulk(db, items)
    for job in created:
        _emit_job(job)
    return BulkJobResponse(
        created=created,
        failed=[BulkJobResultItem(**f) for f in failed],
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = job_service.cancel(db, job)
        _emit_job(job)
        return job
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = job_service.retry(db, job)
        _emit_job(job)
        return job
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{job_id}/republish/preview", response_model=RepublishPreviewResponse)
def republish_preview(
    job_id: int,
    payload: RepublishRequest,
    db: Session = Depends(get_db),
) -> RepublishPreviewResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        preview = job_service.preview_republish(db, job, rewrite=payload.rewrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RepublishPreviewResponse(**preview)


@router.post("/{job_id}/republish", response_model=RepublishResponse)
def republish_job(
    job_id: int,
    payload: RepublishRequest,
    db: Session = Depends(get_db),
) -> RepublishResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        result = job_service.republish(
            db,
            job,
            rewrite=payload.rewrite,
            scheduled_at=payload.scheduled_at,
            max_retries=payload.max_retries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_job = result["new_job"]
    _emit_job(new_job)
    return RepublishResponse(**result)


@router.get("/{job_id}/detail", response_model=JobDetailResponse)
def job_detail(job_id: int, db: Session = Depends(get_db)) -> JobDetailResponse:
    detail = job_service.get_job_detail(db, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetailResponse(
        job=detail["job"],
        steps=detail["steps"],
        totals=JobDetailTotals(**detail["totals"]),
        account_id=detail["account_id"],
    )


@router.post("/{job_id}/resume", response_model=JobResponse)
def resume_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = job_service.resume_from_human(db, job)
        _emit_job(job)
        return job
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{job_id}/logs", response_model=list[ExecutionLogResponse])
def job_logs(job_id: int, db: Session = Depends(get_db)) -> list[ExecutionLogResponse]:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.get_logs(db, job_id)
