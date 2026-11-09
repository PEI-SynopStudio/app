import asyncio

from typing import Tuple

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue
from aio_pika.exceptions import AMQPError

from app.core.config import (
    BROKER_CONTENT_TYPE,
    BROKER_PUBLISH_TIMEOUT_SECONDS,
    ERROR_JOB_DISPATCH_FAILED,
    JOB_EVENTS_EXCHANGE,
    JOB_EVENTS_QUEUE,
    JOB_EVENTS_ROUTING_KEY,
    JOBS_EXCHANGE,
    JOBS_QUEUE_FORMAT,
    MEDIA_EVENTS_EXCHANGE,
    MEDIA_INGESTED_EVENT,
    MEDIA_INGESTED_QUEUE,
)
from app.core.exceptions import JobDispatchError
from app.schemas.job import JobRequestMessage
from app.services.workflow.dispatcher import JobDispatcher


async def declare_job_queue(channel: AbstractChannel, job_type: str) -> Tuple[AbstractExchange, AbstractQueue]:
    """Declared by both sides, so a job published before its worker starts waits in the queue."""
    exchange = await channel.declare_exchange(JOBS_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(JOBS_QUEUE_FORMAT.format(job_type=job_type), durable=True)
    await queue.bind(exchange, job_type)
    return exchange, queue


async def declare_event_queue(channel: AbstractChannel) -> Tuple[AbstractExchange, AbstractQueue]:
    """Worker to backend; the queue keeps the events while the backend is not reading them."""
    exchange = await channel.declare_exchange(JOB_EVENTS_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(JOB_EVENTS_QUEUE, durable=True)
    await queue.bind(exchange, JOB_EVENTS_ROUTING_KEY)
    return exchange, queue


async def declare_media_events_exchange(channel: AbstractChannel) -> AbstractExchange:
    """The queue keeps media.ingested until the transcription worker exists and reads it (FR04, FR05)."""
    exchange = await channel.declare_exchange(MEDIA_EVENTS_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(MEDIA_INGESTED_QUEUE, durable=True)
    await queue.bind(exchange, MEDIA_INGESTED_EVENT)
    return exchange


# Publish each job to the durable jobs exchange, with its type as the routing key.
# Source: architecture §2 (job queue between backend and workers); MS2 FR02 – Outputs (asynchronous ingestion).
class RabbitMQDispatcher(JobDispatcher):
    """Opens one short connection per job: submissions are rare and the API endpoints are synchronous."""

    def __init__(self, url: str) -> None:
        self._url = url

    def dispatch(self, request: JobRequestMessage) -> None:
        """Returns once the broker has confirmed the message; raises JobDispatchError otherwise."""
        try:
            asyncio.run(asyncio.wait_for(self._publish(request), BROKER_PUBLISH_TIMEOUT_SECONDS))
        except (AMQPError, OSError) as exc:  # a timeout is an OSError too
            raise JobDispatchError(ERROR_JOB_DISPATCH_FAILED) from exc

    async def _publish(self, request: JobRequestMessage) -> None:
        job_type = request.parameters.job_type
        connection = await aio_pika.connect(self._url)
        async with connection:
            exchange, _ = await declare_job_queue(await connection.channel(), job_type)
            message = aio_pika.Message(
                body=request.model_dump_json().encode(),
                content_type=BROKER_CONTENT_TYPE,
                message_id=str(request.job_id),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await exchange.publish(message, job_type)
