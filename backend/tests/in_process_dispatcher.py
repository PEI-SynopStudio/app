"""Stand-in for the broker and the worker in API tests: runs the real pipeline in a thread of the test process."""
import threading
from datetime import datetime, timezone

from app.core.config import JobStatusEnum
from app.services.video.metadata import IngestionOutput
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.event_consumer import MediaIngestedEvent
from app.services.workflow.ingestion_pipeline import run_ingestion
from app.services.workflow.jobs import apply_job_event


class InProcessDispatcher(JobDispatcher):
    def __init__(self, storage, object_storage, session_factory, publish_event):
        self._storage = storage
        self._object_storage = object_storage
        self._session_factory = session_factory
        self._publish_event = publish_event
        self._threads = []

    def dispatch(self, request):
        thread = threading.Thread(target=self._run, args=(request,), daemon=True)
        self._threads.append(thread)
        thread.start()

    def join(self, timeout=None):
        """Wait for the running jobs."""
        for thread in self._threads:
            thread.join(timeout)

    def _apply_event(self, event):
        with self._session_factory() as db:
            apply_job_event(db, event)

    def _run(self, request):
        final = run_ingestion(self._storage, self._object_storage, request, self._apply_event)
        if final.status == JobStatusEnum.COMPLETED:
            output = IngestionOutput.model_validate(final.output)
            self._publish_event(MediaIngestedEvent(
                job_id=request.job_id,
                project_id=request.project_id,
                audio_path=output.audio_key,
                proxy_path=output.proxy_key,
                occurred_at=datetime.now(timezone.utc),
            ))
