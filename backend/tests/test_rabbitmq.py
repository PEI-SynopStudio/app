import asyncio
import os
import uuid

import aio_pika
import pytest
from aio_pika.exceptions import AMQPError

from app.core.exceptions import JobDispatchError
from app.schemas.job import IngestionParams, JobRequestMessage
from app.services.workflow import rabbitmq as rabbitmq_module
from app.services.workflow.rabbitmq import RabbitMQDispatcher, get_dispatcher

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
    dlx = f"test-dlx-{suffix}"
    dlq = f"test-dlq-{suffix}"
    monkeypatch.setattr(rabbitmq_module, "JOBS_EXCHANGE", f"test-jobs-{suffix}")
    monkeypatch.setattr(rabbitmq_module, "JOBS_QUEUE_FORMAT", f"test-jobs-{suffix}.{{job_type}}")
    monkeypatch.setattr(rabbitmq_module, "DEAD_LETTER_EXCHANGE", dlx)
    monkeypatch.setattr(rabbitmq_module, "DEAD_LETTER_QUEUE", dlq)
    name = f"test-jobs-{suffix}.ingestion"
    yield name

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            await channel.queue_delete(name)
            await channel.exchange_delete(f"test-jobs-{suffix}")
            await channel.queue_delete(dlq)
            await channel.exchange_delete(dlx)

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


def test_the_api_publishes_jobs_to_the_broker():
    get_dispatcher.cache_clear()
    try:
        assert isinstance(get_dispatcher(), RabbitMQDispatcher)
    finally:
        get_dispatcher.cache_clear()


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


def test_rejected_job_message_routed_dlq(queue_name):
    request = job_request()
    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(request)
    
    async def reject_one():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True, passive=True)
            message = await queue.get(no_ack=False, timeout=2)
            await message.reject(requeue=False)
            
    asyncio.run(reject_one())
    dead_letters = read_messages(rabbitmq_module.DEAD_LETTER_QUEUE)
    
    assert len(dead_letters) == 1
    assert JobRequestMessage.model_validate_json(dead_letters[0].body) == request
    

def test_dead_letter_queue_drops_oldest_messages_when_max_length_is_exceeded(queue_name, monkeypatch):
    monkeypatch.setattr(rabbitmq_module, "DEAD_LETTER_MAX_LENGTH", 2)
    dispatcher = RabbitMQDispatcher(TEST_RABBITMQ_URL)
    requests = [job_request(), job_request(), job_request()]
    for req in requests:
        dispatcher.dispatch(req)

    async def reject_all():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True, passive=True)
            while (message := await queue.get(no_ack=False, fail=False, timeout=2)) is not None:
                await message.reject(requeue=False)

    asyncio.run(reject_all())
    dead_letters = [JobRequestMessage.model_validate_json(m.body) for m in read_messages(rabbitmq_module.DEAD_LETTER_QUEUE)]
    assert dead_letters == requests[1:]