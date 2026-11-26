import asyncio
import logging

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from aio_pika.exceptions import CONNECTION_EXCEPTIONS
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    EVENT_CONSUMER_PREFETCH,
    EVENT_CONSUMER_RETRY_SECONDS,
    LOG_MEDIA_EVENT_INVALID,
    LOG_TRANSCRIPTION_ALREADY_REQUESTED,
    LOG_TRANSCRIPTION_NO_VIDEO,
    LOG_TRANSCRIPTION_NOT_STARTED,
    LOG_TRIGGER_FAILED,
    LOG_TRIGGER_UNAVAILABLE,
    JobTypeEnum,
)
from app.core.exceptions import JobDispatchError
from app.database.models import Job, MediaAsset
from app.services.projects.projects import LicenceNotConfirmedError, ProjectNotFoundError
from app.services.video.playback import MediaNotReadyError
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.event_consumer import MediaIngestedEvent
from app.services.workflow.jobs import TranscriptionAlreadyRunningError
from app.services.workflow.rabbitmq import declare_media_ingested_queue
from app.services.workflow.submission import submit_transcription

logger = logging.getLogger(__name__)

_NOT_STARTED = (
    TranscriptionAlreadyRunningError,
    LicenceNotConfirmedError,
    ProjectNotFoundError,
    MediaNotReadyError,
    JobDispatchError,
)


class TranscriptionTrigger:

    def __init__(self, url: str, session_factory: sessionmaker[Session], dispatcher: JobDispatcher) -> None:
        self._url = url
        self._session_factory = session_factory
        self._dispatcher = dispatcher

    async def run(self) -> None:
        while True:
            try:
                connection = await aio_pika.connect(self._url)
                lost = asyncio.Event()
                connection.close_callbacks.add(lambda *_: lost.set())
                async with connection:
                    await self.open(await connection.channel())
                    await lost.wait()
            except CONNECTION_EXCEPTIONS as exc:
                logger.warning(LOG_TRIGGER_UNAVAILABLE, exc)
            await asyncio.sleep(EVENT_CONSUMER_RETRY_SECONDS)

    async def open(self, channel: AbstractChannel) -> None:
        await channel.set_qos(prefetch_count=EVENT_CONSUMER_PREFETCH)
        queue = await declare_media_ingested_queue(channel)
        await queue.consume(self.handle)

    async def handle(self, message: AbstractIncomingMessage) -> None:
        try:
            event = MediaIngestedEvent.model_validate_json(message.body)
        except ValidationError:
            logger.error(LOG_MEDIA_EVENT_INVALID, message.message_id)
            await message.reject(requeue=False)
            return

        try:
            await asyncio.to_thread(self.start_transcription, event)
        except (SQLAlchemyError, *CONNECTION_EXCEPTIONS) as exc:
            logger.warning(LOG_TRIGGER_UNAVAILABLE, exc)
            await asyncio.sleep(EVENT_CONSUMER_RETRY_SECONDS)
            await message.nack(requeue=True)
        except Exception:
            logger.exception(LOG_TRIGGER_FAILED, event.job_id)
            await message.reject(requeue=False)
        else:
            await message.ack()

    def start_transcription(self, event: MediaIngestedEvent) -> None:
        with self._session_factory() as db:
            ingestion = db.get(Job, event.job_id)
            asset = db.get(MediaAsset, ingestion.media_asset_id) if ingestion and ingestion.media_asset_id else None
            if asset is None:
                logger.warning(LOG_TRANSCRIPTION_NO_VIDEO, event.job_id)
                return
            requested = select(Job.id).where(Job.media_asset_id == asset.id, Job.job_type == JobTypeEnum.TRANSCRIPTION)
            if db.scalar(requested) is not None:
                logger.info(LOG_TRANSCRIPTION_ALREADY_REQUESTED, event.job_id)
                return
            try:
                submit_transcription(db, self._dispatcher, asset)
            except _NOT_STARTED as exc:
                logger.warning(LOG_TRANSCRIPTION_NOT_STARTED, event.job_id, exc)
