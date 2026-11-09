import asyncio
import logging
import time

import aio_pika
from aio_pika.abc import AbstractChannel
from aio_pika.exceptions import CONNECTION_EXCEPTIONS
from pydantic import ValidationError

from app.core.config import (
    BROKER_CONTENT_TYPE,
    BROKER_PUBLISH_TIMEOUT_SECONDS,
    JOB_EVENTS_ROUTING_KEY,
    LOG_FORMAT,
    LOG_WORKER_BROKER_UNAVAILABLE,
    LOG_WORKER_INVALID_MESSAGE,
    LOG_WORKER_JOB_CRASHED,
    WORKER_EVENT_RETRY_INTERVAL_SECONDS,
    WORKER_EVENT_RETRY_SECONDS,
    WORKER_POLL_INTERVAL_SECONDS,
    JobTypeEnum,
    get_settings,
)
from app.schemas.job import JobRequestMessage, JobUpdateEventSchema
from app.services.storage.local import LocalStorage, get_storage
from app.services.workflow.ingestion_pipeline import run_ingestion
from app.services.workflow.rabbitmq import declare_event_queue, declare_job_queue

logger = logging.getLogger(__name__)


# Take ingestion jobs one at a time, run the pipeline and publish its events to the backend.
# Source: architecture §2 (workers publish results back); MS2 FR02 – Steps 2 to 6.
class IngestionWorker:
    """Never touches PostgreSQL: everything the backend needs travels in the events."""

    def __init__(self, url: str, storage: LocalStorage) -> None:
        self._url = url
        self._storage = storage

    async def run(self) -> None:
        connection = await aio_pika.connect_robust(self._url)
        async with connection:
            await self.open(await connection.channel())
            while True:
                try:
                    found = await self.process_next()
                except CONNECTION_EXCEPTIONS as exc:
                    # The robust connection comes back by itself; a job not yet acknowledged stays in the queue.
                    logger.warning(LOG_WORKER_BROKER_UNAVAILABLE, exc)
                    found = False
                if not found:
                    await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)

    async def open(self, channel: AbstractChannel) -> None:
        self._loop = asyncio.get_running_loop()
        self._events, _ = await declare_event_queue(channel)
        _, self._queue = await declare_job_queue(channel, JobTypeEnum.INGESTION.value)

    async def process_next(self) -> bool:
        """Run the next job, if any; returns False when the queue is empty.

        Jobs are fetched one by one instead of consumed as a stream: a second message delivered while a
        4 h job runs would stay unacknowledged and hit the broker's consumer timeout (30 min).
        """
        message = await self._queue.get(fail=False)
        if message is None:
            return False

        try:
            request = JobRequestMessage.model_validate_json(message.body)
        except ValidationError:
            logger.error(LOG_WORKER_INVALID_MESSAGE, message.message_id)
            await message.reject(requeue=False)
            return True

        # No automatic retries: a worker that dies leaves the job processing until the sweep marks it as timeout.
        await message.ack()
        try:
            await asyncio.to_thread(run_ingestion, self._storage, request, self._emit)
        except Exception:
            # The pipeline has already reported the failure; the worker stays up for the next job.
            logger.exception(LOG_WORKER_JOB_CRASHED, request.job_id)
        return True

    def _emit(self, event: JobUpdateEventSchema) -> None:
        """Called from the pipeline thread; returns once the broker has confirmed the event.

        Retried for a while, so a short broker outage does not lose hours of work. A repeated event is harmless:
        the backend ignores events that change nothing.
        """
        deadline = time.monotonic() + WORKER_EVENT_RETRY_SECONDS
        while True:
            future = asyncio.run_coroutine_threadsafe(self._publish_event(event), self._loop)
            try:
                future.result(BROKER_PUBLISH_TIMEOUT_SECONDS)
                return
            except CONNECTION_EXCEPTIONS as exc:  # a timeout is an OSError too
                if time.monotonic() >= deadline:
                    raise
                logger.warning(LOG_WORKER_BROKER_UNAVAILABLE, exc)
                time.sleep(WORKER_EVENT_RETRY_INTERVAL_SECONDS)

    async def _publish_event(self, event: JobUpdateEventSchema) -> None:
        message = aio_pika.Message(
            body=event.model_dump_json().encode(),
            content_type=BROKER_CONTENT_TYPE,
            message_id=str(event.event_id),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._events.publish(message, JOB_EVENTS_ROUTING_KEY)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    asyncio.run(IngestionWorker(get_settings().rabbitmq_url, get_storage()).run())


if __name__ == "__main__":
    main()
