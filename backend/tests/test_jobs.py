import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Callable, Dict, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    AUDIO_DIR,
    AUDIO_FILE,
    ERROR_INGESTION_ALREADY_RUNNING,
    INGESTION_THREAD_NAME,
    JSON_DUMP_MODE,
    LOG_EVENT_PUBLISHED,
    LOG_JOB_CRASHED,
    MEDIA_INGESTED_EVENT,
    METADATA_FILE,
    PROXY_DIR,
    PROXY_FILE,
    STAGE_MESSAGES,
    IngestionStage,
)
from app.database.session import get_session_factory
from app.services.projects.projects import require_ingestion_allowed
from app.services.storage.local import LocalStorage, get_storage
from app.services.workflow.ingestion_pipeline import IngestionJob, ProgressCallback, run_ingestion
from app.services.workflow.jobs import IngestionAlreadyRunningError
from app.services.workflow.status import IngestionStatus, set_stage

logger = logging.getLogger(__name__)


class MediaIngestedEvent(BaseModel):
    """Published when ingestion completes; triggers transcription and diarization (FR04, FR05)."""
    event: str = MEDIA_INGESTED_EVENT
    project_id: str
    # Paths relative to the project directory, so consumers do not depend on the storage backend.
    audio_path: str
    proxy_path: str
    metadata_path: str
    occurred_at: datetime


EventPublisher = Callable[[MediaIngestedEvent], None]


def log_event(event: MediaIngestedEvent) -> None:
    """Placeholder publisher: logs the event until it is sent to RabbitMQ."""
    logger.info(LOG_EVENT_PUBLISHED, event.event, event.model_dump(mode=JSON_DUMP_MODE))


class JobDispatcher(ABC):
    """What the API depends on; the RabbitMQ publisher will be another implementation."""

    @abstractmethod
    def dispatch(self, job: IngestionJob) -> IngestionStatus:
        """Queue the job and return at once with the 'queued' status; never runs the pipeline inline."""


# Run each ingestion job in a background thread so the API answers immediately.
# Source: MS2 FR02 – Outputs (asynchronous ingestion, event triggers transcription); temporary until the RabbitMQ worker.
class InProcessDispatcher(JobDispatcher):
    """Temporary dispatcher for the prototype: one thread per job, at most one running job per project.

    Running jobs live only in memory: they are lost if the process stops, and their status
    stays at the last stage reached. A RabbitMQ worker with acknowledgements fixes both.
    """

    def __init__(
        self,
        storage: LocalStorage,
        session_factory: sessionmaker[Session],
        publish_event: EventPublisher = log_event,
        on_progress: Optional[ProgressCallback] = None,
    ):
        self._storage = storage
        self._session_factory = session_factory
        self._publish_event = publish_event
        self._on_progress = on_progress
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}

    def dispatch(self, job: IngestionJob) -> IngestionStatus:
        # Checked here too so the API can refuse at once (FR01); the pipeline checks again.
        with self._session_factory() as db:
            require_ingestion_allowed(db, job.project_id)

        with self._lock:
            if self.is_running(job.project_id):
                raise IngestionAlreadyRunningError(
                    ERROR_INGESTION_ALREADY_RUNNING.format(project_id=job.project_id)
                )
            status = set_stage(
                self._storage, job.project_id, IngestionStage.QUEUED, STAGE_MESSAGES[IngestionStage.QUEUED]
            )
            thread = threading.Thread(
                target=self._run,
                args=(job,),
                name=INGESTION_THREAD_NAME.format(project_id=job.project_id),
                # Daemon: a stopping server does not wait for a 4 h job.
                daemon=True,
            )
            self._threads[job.project_id] = thread
            thread.start()
        return status

    def is_running(self, project_id: str) -> bool:
        thread = self._threads.get(project_id)
        return thread is not None and thread.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the running jobs (used by tests)."""
        for thread in list(self._threads.values()):
            thread.join(timeout)

    def _run(self, job: IngestionJob) -> None:
        try:
            status = run_ingestion(self._storage, job, self._on_progress)
            if status.stage == IngestionStage.COMPLETED:
                self._publish_event(_media_ingested(job.project_id))
        except Exception:
            # Nothing above the thread would see the error, so it is logged here.
            logger.exception(LOG_JOB_CRASHED, job.project_id)


def _media_ingested(project_id: str) -> MediaIngestedEvent:
    return MediaIngestedEvent(
        project_id=project_id,
        audio_path=PurePosixPath(AUDIO_DIR, AUDIO_FILE).as_posix(),
        proxy_path=PurePosixPath(PROXY_DIR, PROXY_FILE).as_posix(),
        metadata_path=METADATA_FILE,
        occurred_at=datetime.now(timezone.utc),
    )


@lru_cache
def get_dispatcher() -> JobDispatcher:
    """One dispatcher per process (FastAPI dependency); swap the class here for the RabbitMQ one."""
    return InProcessDispatcher(get_storage(), get_session_factory())
