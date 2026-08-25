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
    JobResponse,
)
from app.services.job_service import job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
def list_jobs(status: str | None = None, db: Session = Depends(get_db)) -> list[JobResponse]:
    return job_service.list_jobs(db, status=status)


@router.post("", response_model=JobResponse)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> JobResponse:
    scheduled_at = payload.scheduled_at or utcnow()
    try:
        return job_service.create(
            db,
            content_variant_id=payload.content_variant_id,
            account_id=payload.account_id,
            scheduled_at=scheduled_at,
            max_retries=payload.max_retries,
        )
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
        return job_service.cancel(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.retry(db, job)


@router.get("/{job_id}/logs", response_model=list[ExecutionLogResponse])
def job_logs(job_id: int, db: Session = Depends(get_db)) -> list[ExecutionLogResponse]:
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.get_logs(db, job_id)
