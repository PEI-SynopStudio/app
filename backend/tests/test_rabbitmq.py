import asyncio
import os
import uuid

import aio_pika
import pytest
from aio_pika.exceptions import AMQPError

from app.core.exceptions import JobDispatchError
from app.schemas.job import IngestionParams, JobRequestMessage
from app.services.workflow import rabbitmq as rabbitmq_module
from app.services.workflow.rabbitmq import RabbitMQDispatcher

TEST_RABBITMQ_URL = os.environ.get("TEST_RABBITMQ_URL", "amqp://pei:pei@localhost:5672/")
UNREACHABLE_URL = "amqp://pei:pei@127.0.0.1:1/"
SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"


def job_request():
    return JobRequestMessage(job_id=uuid.uuid4(), project_id=uuid.uuid4(), parameters=IngestionParams(source_url=SAMPLE_URL))


def broker_is_running():
    async def probe():
        await (await aio_pika.connect(TEST_RABBITMQ_URL, timeout=2)).close()

    try:
        asyncio.run(probe())
    except (AMQPError, OSError):
        return False
    return True


@pytest.fixture
def queue_name(monkeypatch):
    """Publish to an exchange and a queue of this test only, removed at the end."""
    if not broker_is_running():
        pytest.skip("RabbitMQ is not available; run 'docker compose up -d rabbitmq' first")
    suffix = uuid.uuid4().hex
    monkeypatch.setattr(rabbitmq_module, "JOBS_EXCHANGE", f"test-jobs-{suffix}")
    monkeypatch.setattr(rabbitmq_module, "JOBS_QUEUE_FORMAT", f"test-jobs-{suffix}.{{job_type}}")
    name = f"test-jobs-{suffix}.ingestion"
    yield name

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            await channel.queue_delete(name)
            await channel.exchange_delete(f"test-jobs-{suffix}")

    asyncio.run(remove())


def read_messages(queue_name):
    async def read():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True, passive=True)
            messages = []
            while (message := await queue.get(no_ack=True, fail=False, timeout=2)) is not None:
                messages.append(message)
            return messages

    return asyncio.run(read())


def test_job_is_published_to_the_queue_of_its_type(queue_name):
    request = job_request()

    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(request)

    messages = read_messages(queue_name)
    assert len(messages) == 1
    assert JobRequestMessage.model_validate_json(messages[0].body) == request
    assert messages[0].routing_key == "ingestion"
    assert messages[0].message_id == str(request.job_id)
    assert messages[0].content_type == "application/json"
    assert messages[0].delivery_mode == aio_pika.DeliveryMode.PERSISTENT


def test_jobs_wait_in_the_queue_until_a_worker_reads_them(queue_name):
    dispatcher = RabbitMQDispatcher(TEST_RABBITMQ_URL)

    dispatcher.dispatch(job_request())
    dispatcher.dispatch(job_request())

    assert len(read_messages(queue_name)) == 2


def test_wrong_credentials_are_a_dispatch_error(queue_name):
    url = TEST_RABBITMQ_URL.replace("pei:pei", "pei:wrong")

    with pytest.raises(JobDispatchError, match="could not be queued"):
        RabbitMQDispatcher(url).dispatch(job_request())


def test_unreachable_broker_is_a_dispatch_error():
    with pytest.raises(JobDispatchError, match="could not be queued"):
        RabbitMQDispatcher(UNREACHABLE_URL).dispatch(job_request())


def test_slow_broker_is_a_dispatch_error(monkeypatch):
    async def never_answers(self, request):
        await asyncio.sleep(60)

    monkeypatch.setattr(RabbitMQDispatcher, "_publish", never_answers)
    monkeypatch.setattr(rabbitmq_module, "BROKER_PUBLISH_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(JobDispatchError):
        RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(job_request())
