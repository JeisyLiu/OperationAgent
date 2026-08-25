import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.content import router as content_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.settings import router as settings_router
from app.api.platforms import router as platforms_router
from app.api.worker import router as worker_router
from app.config import APP_VERSION, settings
from app.db.migrate import run_migrations
from app.scheduler.worker import worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations()
    await worker.start()
    yield
    await worker.stop()


app = FastAPI(
    title="OperationAgent",
    version=APP_VERSION,
    description="Local AI social media operator (single-machine MVP)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(settings_router)
app.include_router(accounts_router)
app.include_router(content_router)
app.include_router(jobs_router)
app.include_router(platforms_router)
app.include_router(worker_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
