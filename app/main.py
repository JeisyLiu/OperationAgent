import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: Playwright needs ProactorEventLoop for subprocess spawn.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.skills import router as skills_router
from app.api.accounts import router as accounts_router
from app.api.content import router as content_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.jobs import router as jobs_router
from app.api.llm_models import router as llm_models_router
from app.api.settings import router as settings_router
from app.api.promo import router as promo_router
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
    from app.agent.factory import default_adapter_name
    from app.db.models import Base
    from app.db.session import engine
    from app.services.chrome_manager import ensure_cdp_ready, shutdown_managed_chrome
    from app.services.event_bus import set_main_loop

    set_main_loop(asyncio.get_running_loop())
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_migrations()

    if default_adapter_name() == "chrome_devtools":
        ok, msg = ensure_cdp_ready()
        if ok:
            logging.getLogger(__name__).info("CDP ready: %s", msg)
        else:
            logging.getLogger(__name__).warning("CDP not ready at startup: %s", msg)

    await worker.start()
    yield
    await worker.stop()
    shutdown_managed_chrome()


app = FastAPI(
    title="OperationAgent",
    version=APP_VERSION,
    description="Local AI social media operator (single-machine MVP)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(events_router)
app.include_router(settings_router)
app.include_router(llm_models_router)
app.include_router(skills_router)
app.include_router(accounts_router)
app.include_router(content_router)
app.include_router(jobs_router)
app.include_router(history_router)
app.include_router(promo_router)
app.include_router(platforms_router)
app.include_router(worker_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
