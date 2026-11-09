import asyncio
import logging

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import LOG_SWEEP_DONE, LOG_SWEEP_FAILED, get_settings
from app.services.storage.local import LocalStorage
from app.services.video.uploads import purge_expired_uploads
from app.services.workflow.jobs import sweep_stalled_jobs

logger = logging.getLogger(__name__)


# Periodically close the jobs whose worker went silent and remove the uploads that were abandoned.
# Source: MS2 FR02 – Step 3 ('Ingestion Failed' with details); project plan decision 7 (no retries, periodic sweep).
async def run_periodic_sweep(session_factory: sessionmaker[Session], storage: LocalStorage) -> None:
    """Runs until cancelled. Waits first: events queued while the API was down must be applied before judging a job."""
    while True:
        await asyncio.sleep(get_settings().sweep_interval_seconds)
        try:
            await asyncio.to_thread(sweep_once, session_factory, storage)
        except Exception:
            # The next round tries again; a failed sweep must not end the task.
            logger.exception(LOG_SWEEP_FAILED)


def sweep_once(session_factory: sessionmaker[Session], storage: LocalStorage) -> None:
    with session_factory() as db:
        stalled = sweep_stalled_jobs(db)
        expired = purge_expired_uploads(db, storage)
    if stalled or expired:
        logger.info(LOG_SWEEP_DONE, stalled, expired)
