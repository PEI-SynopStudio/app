import asyncio
import logging
from typing import Callable, List

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import LOG_SWEEP_DONE, LOG_SWEEP_FAILED, LOG_SWEEP_PURGE_FAILED, get_settings
from app.schemas.job import JobStatusResponseSchema
from app.services.storage.object_storage import ObjectStorage, ObjectStorageError
from app.services.video.uploads import purge_expired_uploads
from app.services.workflow.jobs import sweep_stalled_jobs
from app.services.workflow.progress_hub import JobProgressHub

logger = logging.getLogger(__name__)


# Periodically close the jobs whose worker went silent and remove the uploads that were abandoned.
# Source: MS2 FR02 – Step 3 ('Ingestion Failed' with details); project plan decision 7 (no retries, periodic sweep).
async def run_periodic_sweep(
    session_factory: sessionmaker[Session], open_object_storage: Callable[[], ObjectStorage], hub: JobProgressHub
) -> None:
    """Runs until cancelled. Waits first: events queued while the API was down must be applied before judging a job."""
    while True:
        await asyncio.sleep(get_settings().sweep_interval_seconds)
        try:
            for update in await asyncio.to_thread(sweep_once, session_factory, open_object_storage):
                hub.publish(update)
        except Exception:
            # The next round tries again; a failed sweep must not end the task.
            logger.exception(LOG_SWEEP_FAILED)


def sweep_once(
    session_factory: sessionmaker[Session], open_object_storage: Callable[[], ObjectStorage]
) -> List[JobStatusResponseSchema]:
    """Returns the new state of the jobs it failed, for the clients watching them."""
    with session_factory() as db:
        stalled = sweep_stalled_jobs(db)
        # A storage outage must not hide the jobs just failed from the clients watching them.
        try:
            expired = purge_expired_uploads(db, open_object_storage())
        except ObjectStorageError:
            logger.exception(LOG_SWEEP_PURGE_FAILED)
            expired = 0
    if stalled or expired:
        logger.info(LOG_SWEEP_DONE, len(stalled), expired)
    return stalled
