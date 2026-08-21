from fastapi import APIRouter

from app.scheduler.worker import worker

router = APIRouter(prefix="/api/worker", tags=["worker"])


@router.get("/status")
def worker_status() -> dict:
    return worker.get_status()


@router.post("/pause")
async def pause_worker() -> dict:
    await worker.pause_current()
    return {"ok": True, **worker.get_status()}


@router.post("/stop")
async def stop_agent() -> dict:
    await worker.stop_current()
    return {"ok": True, **worker.get_status()}
