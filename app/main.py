from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.accounts import router as accounts_router
from app.api.content import router as content_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.settings import router as settings_router
from app.config import APP_VERSION, settings
from app.scheduler.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
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
