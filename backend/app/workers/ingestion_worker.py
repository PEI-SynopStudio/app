import asyncio
import logging

from app.core.config import LOG_FORMAT, JobTypeEnum, get_settings
from app.schemas.job import JobRequestMessage
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage
from app.services.workflow.ingestion_pipeline import run_ingestion
from app.workers.job_worker import JobWorker


# Take ingestion jobs one at a time, run the pipeline and publish its events to the backend.
# Source: architecture §2 (workers publish results back); MS2 FR02 – Steps 2 to 6.
class IngestionWorker(JobWorker):
    job_type = JobTypeEnum.INGESTION

    def __init__(self, url: str, storage: LocalStorage, object_storage: ObjectStorage) -> None:
        super().__init__(url)
        self._storage = storage
        self._object_storage = object_storage

    def run_job(self, request: JobRequestMessage) -> None:
        run_ingestion(self._storage, self._object_storage, request, self._emit)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    asyncio.run(IngestionWorker(get_settings().rabbitmq_url, get_storage(), get_object_storage()).run())


if __name__ == "__main__":
    main()
