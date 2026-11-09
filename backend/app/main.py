import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import ingestion, jobs, progress, projects, uploads
from app.api.errors import storage_unavailable
from app.core.config import APP_LOGGER_NAME, APP_TITLE, HEALTH_OK, HEALTH_ROUTE, LOG_FORMAT, get_settings
from app.database.session import get_session_factory
from app.services.storage.local import get_storage
from app.services.storage.object_storage import ObjectStorageError
from app.services.workflow.event_consumer import JobEventConsumer
from app.services.workflow.progress_hub import get_progress_hub
from app.services.workflow.sweeper import run_periodic_sweep


def _configure_logging() -> None:
    """Show the application's INFO logs (e.g. published events); uvicorn configures only its own loggers."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(get_settings().log_level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    hub = get_progress_hub()
    tasks = [
        asyncio.create_task(JobEventConsumer(get_settings().rabbitmq_url, get_session_factory(), hub).run()),
        asyncio.create_task(run_periodic_sweep(get_session_factory(), get_storage(), hub)),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


_configure_logging()
app = FastAPI(title=APP_TITLE, lifespan=_lifespan)
app.add_exception_handler(ObjectStorageError, storage_unavailable)
app.include_router(projects.router)
app.include_router(ingestion.router)
app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(progress.router)

@app.get(HEALTH_ROUTE)
def health():
    return {"status": HEALTH_OK}
