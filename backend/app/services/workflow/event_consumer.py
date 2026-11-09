import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from aio_pika.exceptions import CONNECTION_EXCEPTIONS
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    BROKER_CONTENT_TYPE,
    EVENT_CONSUMER_PREFETCH,
    EVENT_CONSUMER_RETRY_SECONDS,
    LOG_EVENT_CONSUMER_UNAVAILABLE,
    LOG_EVENT_INVALID,
    LOG_EVENT_NOT_APPLIED,
    LOG_EVENT_UNKNOWN_JOB,
    MEDIA_INGESTED_EVENT,
    JobStatusEnum,
    JobTypeEnum,
)
from app.core.exceptions import JobNotFoundError
from app.database.models import Job
from app.schemas.job import JobUpdateEventSchema
from app.services.video.metadata import IngestionOutput
from app.services.workflow.jobs import apply_job_event
from app.services.workflow.rabbitmq import declare_event_queue, declare_media_events_exchange

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


# Apply the events of the workers to the database and announce the finished ingestions.
# Source: architecture §2 (workers publish results, the backend persists them); MS2 FR02 – Outputs (event triggers transcription).
class JobEventConsumer:
    """Runs inside the API process; prefetch 1 applies the events strictly in the order they were published."""

    def __init__(self, url: str, session_factory: sessionmaker[Session]) -> None:
        self._url = url
        self._session_factory = session_factory

    async def run(self) -> None:
        """Runs until cancelled, connecting again whenever the connection is lost.

        A plain connection: a robust one cannot be cancelled while it connects, which would hang the API shutdown.
        """
        while True:
            try:
                connection = await aio_pika.connect(self._url)
                lost = asyncio.Event()
                connection.close_callbacks.add(lambda *_: lost.set())
                async with connection:
                    await self.open(await connection.channel())
                    await lost.wait()
            except CONNECTION_EXCEPTIONS as exc:
                logger.warning(LOG_EVENT_CONSUMER_UNAVAILABLE, exc)
            await asyncio.sleep(EVENT_CONSUMER_RETRY_SECONDS)

    async def open(self, channel: AbstractChannel) -> None:
        await channel.set_qos(prefetch_count=EVENT_CONSUMER_PREFETCH)
        self._media_events = await declare_media_events_exchange(channel)
        _, queue = await declare_event_queue(channel)
        await queue.consume(self.handle)

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Acknowledged only after the database commit and the media.ingested publication."""
        try:
            event = JobUpdateEventSchema.model_validate_json(message.body)
        except ValidationError:
            logger.error(LOG_EVENT_INVALID, message.message_id)
            await message.reject(requeue=False)
            return

        try:
            ingested = await asyncio.to_thread(self._apply, event)
            if ingested is not None:
                await self._publish_media_ingested(ingested)
        except JobNotFoundError:
            # The project was deleted while its job was running.
            logger.warning(LOG_EVENT_UNKNOWN_JOB, event.job_id)
            await message.reject(requeue=False)
        except (SQLAlchemyError, *CONNECTION_EXCEPTIONS) as exc:
            # Temporary: back in the queue, and the state machine ignores what was already applied.
            logger.warning(LOG_EVENT_CONSUMER_UNAVAILABLE, exc)
            await asyncio.sleep(EVENT_CONSUMER_RETRY_SECONDS)
            await message.nack(requeue=True)
        except Exception:
            # Retrying cannot fix a bug; the sweep eventually closes a job that loses its final event.
            logger.exception(LOG_EVENT_NOT_APPLIED, event.job_id)
            await message.reject(requeue=False)
        else:
            await message.ack()

    def _apply(self, event: JobUpdateEventSchema) -> Optional[MediaIngestedEvent]:
        """Returns the event to announce; a repeated completed event announces again, consumers use the job ID."""
        with self._session_factory() as db:
            result = apply_job_event(db, event)
            completed = event.status == JobStatusEnum.COMPLETED and result.job.status == JobStatusEnum.COMPLETED
            if not completed or result.job.job_type != JobTypeEnum.INGESTION:
                return None
            output = IngestionOutput.model_validate(result.job.output)
            return MediaIngestedEvent(
                job_id=event.job_id,
                project_id=db.get(Job, event.job_id).project_id,
                audio_path=output.audio_key,
                proxy_path=output.proxy_key,
                occurred_at=datetime.now(timezone.utc),
            )

    async def _publish_media_ingested(self, event: MediaIngestedEvent) -> None:
        message = aio_pika.Message(
            body=event.model_dump_json().encode(),
            content_type=BROKER_CONTENT_TYPE,
            message_id=str(event.job_id),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._media_events.publish(message, MEDIA_INGESTED_EVENT)
