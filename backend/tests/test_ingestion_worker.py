import asyncio
import shutil
import uuid

import aio_pika
import pytest
from aio_pika.exceptions import AMQPError

from app.core.config import JobErrorCodeEnum, JobStatusEnum
from app.schemas.job import IngestionParams, JobRequestMessage, JobUpdateEventSchema
from app.services.storage.local import LocalStorage
from app.services.workflow import rabbitmq as rabbitmq_module
from app.services.workflow.rabbitmq import RabbitMQDispatcher
from app.workers import ingestion_worker
from app.workers.ingestion_worker import IngestionWorker
from test_rabbitmq import TEST_RABBITMQ_URL, broker_is_running


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def queues(monkeypatch):
    """Exchanges and queues of this test only, removed at the end."""
    if not broker_is_running():
        pytest.skip("RabbitMQ is not available; run 'docker compose up -d rabbitmq' first")
    prefix = f"test-{uuid.uuid4().hex}"
    names = {
        "JOBS_EXCHANGE": f"{prefix}-jobs",
        "JOBS_QUEUE_FORMAT": f"{prefix}-jobs.{{job_type}}",
        "JOB_EVENTS_EXCHANGE": f"{prefix}-events",
        "JOB_EVENTS_QUEUE": f"{prefix}-events.queue",
    }
    for constant, value in names.items():
        monkeypatch.setattr(rabbitmq_module, constant, value)
    jobs_queue = names["JOBS_QUEUE_FORMAT"].format(job_type="ingestion")
    yield jobs_queue, names["JOB_EVENTS_QUEUE"]

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            await channel.queue_delete(jobs_queue)
            await channel.queue_delete(names["JOB_EVENTS_QUEUE"])
            await channel.exchange_delete(names["JOBS_EXCHANGE"])
            await channel.exchange_delete(names["JOB_EVENTS_EXCHANGE"])

    asyncio.run(remove())


def process_next(storage):
    """Run the worker for one job, on a connection of its own."""

    async def run():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            worker = IngestionWorker(TEST_RABBITMQ_URL, storage)
            await worker.open(await connection.channel())
            return await worker.process_next()

    return asyncio.run(run())


def read_all(queue_name):
    async def read():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True, passive=True)
            bodies = []
            while (message := await queue.get(no_ack=True, fail=False, timeout=2)) is not None:
                bodies.append(message.body)
            return bodies

    return asyncio.run(read())


def publish_raw(queue_name, body):
    async def publish():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            await channel.default_exchange.publish(aio_pika.Message(body=body), queue_name)

    asyncio.run(publish())


def stage_job(storage, sample):
    """Publish an upload job whose file is already in the project's source directory."""
    project_id = uuid.uuid4()
    shutil.copy(sample, storage.path(str(project_id), "source", "lecture.mp4"))
    request = JobRequestMessage(
        job_id=uuid.uuid4(),
        project_id=project_id,
        parameters=IngestionParams(media_id=uuid.uuid4()),
        staged_file="lecture.mp4",
        file_name="lecture.mp4",
    )
    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(request)
    return request


def events_in(queue_name):
    return [JobUpdateEventSchema.model_validate_json(body) for body in read_all(queue_name)]


def test_worker_runs_the_job_and_publishes_its_events(queues, storage, make_sample):
    jobs_queue, events_queue = queues
    request = stage_job(storage, make_sample(tone=True))

    assert process_next(storage) is True

    events = events_in(events_queue)
    assert {event.job_id for event in events} == {request.job_id}
    assert events[0].status == JobStatusEnum.PROCESSING
    assert events[-1].status == JobStatusEnum.COMPLETED
    assert events[-1].output["proxy_key"] == "proxy/proxy.mp4"
    assert storage.path(str(request.project_id), "proxy", "proxy.mp4").is_file()
    assert read_all(jobs_queue) == []


def test_empty_queue_returns_false(queues, storage):
    assert process_next(storage) is False


def test_rejected_media_is_reported_as_a_failed_event(queues, storage, make_sample):
    _, events_queue = queues
    stage_job(storage, make_sample())  # silent audio

    process_next(storage)

    final = events_in(events_queue)[-1]
    assert (final.status, final.error_code) == (JobStatusEnum.FAILED, JobErrorCodeEnum.SILENT_AUDIO)


def test_worker_takes_one_job_at_a_time(queues, storage, make_sample):
    jobs_queue, _ = queues
    sample = make_sample(tone=True)
    stage_job(storage, sample)
    stage_job(storage, sample)

    process_next(storage)

    assert len(read_all(jobs_queue)) == 1


def test_invalid_message_is_discarded(queues, storage, caplog):
    jobs_queue, events_queue = queues
    process_next(storage)  # declares the queues
    publish_raw(jobs_queue, b"not a job")

    assert process_next(storage) is True

    assert read_all(jobs_queue) == []
    assert read_all(events_queue) == []
    assert "Invalid job message" in caplog.text


def emit_with_failures(monkeypatch, failures):
    """Call the worker's emit with a publisher that fails a number of times first; returns how many calls it took."""
    monkeypatch.setattr(ingestion_worker, "WORKER_EVENT_RETRY_INTERVAL_SECONDS", 0)
    attempts = []

    async def flaky_publish(event):
        attempts.append(event)
        if len(attempts) <= failures:
            raise AMQPError("broker restarting")

    async def run():
        worker = IngestionWorker(TEST_RABBITMQ_URL, None)
        worker._loop = asyncio.get_running_loop()
        worker._publish_event = flaky_publish
        event = JobUpdateEventSchema(job_id=uuid.uuid4(), status=JobStatusEnum.PROCESSING, step_progress=10)
        await asyncio.to_thread(worker._emit, event)

    asyncio.run(run())
    return len(attempts)


def test_event_is_sent_again_while_the_broker_is_restarting(monkeypatch):
    assert emit_with_failures(monkeypatch, failures=3) == 4


def test_event_gives_up_when_the_broker_stays_down(monkeypatch):
    monkeypatch.setattr(ingestion_worker, "WORKER_EVENT_RETRY_SECONDS", 0)

    with pytest.raises(AMQPError):
        emit_with_failures(monkeypatch, failures=1000)


def test_crashed_job_is_not_delivered_again(queues, storage, make_sample, monkeypatch, caplog):
    def crash(storage, request, emit):
        raise KeyError("bug")

    monkeypatch.setattr(ingestion_worker, "run_ingestion", crash)
    stage_job(storage, make_sample(tone=True))

    assert process_next(storage) is True
    assert process_next(storage) is False
    assert "crashed" in caplog.text
