from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import APP_VERSION
from app.db.session import get_db
from app.services.event_bus import emit_readiness_changed
from app.services.readiness_service import heal_and_readiness, run_readiness

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@router.get("/api/health/readiness")
def readiness(db: Session = Depends(get_db)) -> dict:
    return run_readiness(db, auto_heal=False)


@router.post("/api/health/heal")
async def heal(db: Session = Depends(get_db)) -> dict:
    report = await heal_and_readiness(db)
    emit_readiness_changed()
    return report
