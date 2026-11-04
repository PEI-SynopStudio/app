import logging

from fastapi import FastAPI

from app.api import ingestion, projects, uploads
from app.core.config import APP_LOGGER_NAME, APP_TITLE, HEALTH_OK, HEALTH_ROUTE, LOG_FORMAT, get_settings


def _configure_logging() -> None:
    """Show the application's INFO logs (e.g. published events); uvicorn configures only its own loggers."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(get_settings().log_level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)


_configure_logging()
app = FastAPI(title=APP_TITLE)
app.include_router(projects.router)
app.include_router(ingestion.router)
app.include_router(uploads.router)

@app.get(HEALTH_ROUTE)
def health():
    return {"status": HEALTH_OK}
