import logging
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    INGESTION_THREAD_NAME,
    JSON_DUMP_MODE,
    LOG_EVENT_PUBLISHED,
    LOG_JOB_CRASHED,
    MEDIA_INGESTED_EVENT,
    JobStatusEnum,
)
from app.database.session import get_session_factory
from app.schemas.job import JobRequestMessage, JobUpdateEventSchema
from app.services.storage.local import LocalStorage, get_storage
from app.services.video.metadata import IngestionOutput
from app.services.workflow.ingestion_pipeline import run_ingestion
from app.services.workflow.jobs import apply_job_event

logger = logging.getLogger(__name__)


class MediaIngestedEvent(BaseModel):
    """Published when ingestion completes; triggers transcription and diarization (FR04, FR05)."""
    event: str = MEDIA_INGESTED_EVENT
    job_id: uuid.UUID
    project_id: uuid.UUID
    # Paths relative to the project directory, so consumers do not depend on the storage backend.
    audio_path: str
    proxy_path: str
    occurred_at: datetime


EventPublisher = Callable[[MediaIngestedEvent], None]


def log_event(event: MediaIngestedEvent) -> None:
    """Placeholder publisher: logs the event until it is sent to RabbitMQ."""
    logger.info(LOG_EVENT_PUBLISHED, event.event, event.model_dump(mode=JSON_DUMP_MODE))


class JobDispatcher(ABC):
    """What the job submission depends on; the RabbitMQ publisher will be another implementation."""

    @abstractmethod
    def dispatch(self, request: JobRequestMessage) -> None:
        """Hand the job over and return at once; never runs the pipeline inline."""


# Run each ingestion job in a background thread so the API answers immediately.
# Source: MS2 FR02 – Outputs (asynchronous ingestion, event triggers transcription); temporary until the RabbitMQ worker.
class InProcessDispatcher(JobDispatcher):
    """Temporary dispatcher for the prototype: one thread per job.

    Running jobs live only in memory, so they are lost if the process stops.
    """

    def __init__(
        self,
        storage: LocalStorage,
        session_factory: sessionmaker[Session],
        publish_event: EventPublisher = log_event,
    ):
        self._storage = storage
        self._session_factory = session_factory
        self._publish_event = publish_event
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []

    def dispatch(self, request: JobRequestMessage) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(request,),
            name=INGESTION_THREAD_NAME.format(project_id=request.project_id),
            # Daemon: a stopping server does not wait for a 4 h job.
            daemon=True,
        )
        with self._lock:
            self._threads = [running for running in self._threads if running.is_alive()]
            self._threads.append(thread)
        thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the running jobs (used by tests)."""
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(timeout)

    def _apply_event(self, event: JobUpdateEventSchema) -> None:
        with self._session_factory() as db:
            apply_job_event(db, event)

    def _run(self, request: JobRequestMessage) -> None:
        try:
            final = run_ingestion(self._storage, request, self._apply_event)
            if final.status == JobStatusEnum.COMPLETED:
                self._publish_event(_media_ingested(request, final))
        except Exception:
            # Nothing above the thread would see the error, so it is logged here.
            logger.exception(LOG_JOB_CRASHED, request.project_id)


def _media_ingested(request: JobRequestMessage, final: JobUpdateEventSchema) -> MediaIngestedEvent:
    output = IngestionOutput.model_validate(final.output)
    return MediaIngestedEvent(
        job_id=request.job_id,
        project_id=request.project_id,
        audio_path=output.audio_key,
        proxy_path=output.proxy_key,
        occurred_at=datetime.now(timezone.utc),
    )


@lru_cache
def get_dispatcher() -> JobDispatcher:
    """One dispatcher per process (FastAPI dependency); swap the class here for the RabbitMQ one."""
    return InProcessDispatcher(get_storage(), get_session_factory())
