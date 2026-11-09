import asyncio
import json
import logging
import time
import uuid
from datetime import date

import aio_pika
import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, LicenseType, MediaAssetStatus, SourceType
from app.database.models import Job, MediaAsset
from app.schemas.job import IngestionParams, JobRequestMessage, JobUpdateEventSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.storage.local import LocalStorage
from app.services.workflow import event_consumer, rabbitmq as rabbitmq_module
from app.services.workflow.event_consumer import JobEventConsumer
from app.services.workflow.jobs import create_ingestion_job, queue_job
from app.services.workflow.progress_hub import JobProgressHub
from in_memory_object_storage import InMemoryObjectStorage
from app.services.workflow.rabbitmq import RabbitMQDispatcher
from app.workers.ingestion_worker import IngestionWorker
from test_rabbitmq import TEST_RABBITMQ_URL, UNREACHABLE_URL, broker_is_running

WAIT_SECONDS = 20
SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"


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
        "MEDIA_EVENTS_EXCHANGE": f"{prefix}-media",
        "MEDIA_INGESTED_QUEUE": f"{prefix}-media.ingested",
    }
    for constant, value in names.items():
        monkeypatch.setattr(rabbitmq_module, constant, value)
    monkeypatch.setattr(event_consumer, "EVENT_CONSUMER_RETRY_SECONDS", 0.05)
    yield names

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            for queue in (names["JOBS_QUEUE_FORMAT"].format(job_type="ingestion"), names["JOB_EVENTS_QUEUE"], names["MEDIA_INGESTED_QUEUE"]):
                await channel.queue_delete(queue)
            for exchange in (names["JOBS_EXCHANGE"], names["JOB_EVENTS_EXCHANGE"], names["MEDIA_EVENTS_EXCHANGE"]):
                await channel.exchange_delete(exchange)

    asyncio.run(remove())


@pytest.fixture
def job(db):
    """A queued ingestion job with its project and media asset."""
    project = create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    ))
    asset = MediaAsset(project_id=project.id, source_type=SourceType.UPLOAD, status=MediaAssetStatus.PROCESSING)
    db.add(asset)
    db.commit()
    params = IngestionParams(media_id=asset.id)
    return queue_job(db, create_ingestion_job(db, str(project.id), params, "lecture.mp4", media_asset_id=asset.id))


def progress_event(job_id, percent=50.0):
    return JobUpdateEventSchema(
        job_id=job_id, status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INSPECTING_MEDIA, step_progress=percent
    )


def consume(session_factory, bodies, done, hub=None):
    """Publish the raw event bodies, run the consumer until `done()` holds and return the media.ingested bodies."""

    async def run():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            consumer = JobEventConsumer(TEST_RABBITMQ_URL, session_factory, hub or JobProgressHub())
            await consumer.open(channel)
            sender = await connection.channel()
            exchange, _ = await rabbitmq_module.declare_event_queue(sender)
            for body in bodies:
                await exchange.publish(aio_pika.Message(body=body), rabbitmq_module.JOB_EVENTS_ROUTING_KEY)

            deadline = time.monotonic() + WAIT_SECONDS
            while not await asyncio.to_thread(done):
                assert time.monotonic() < deadline, "the consumer did not finish in time"
                await asyncio.sleep(0.05)
            # A message is acknowledged after its database commit.
            await asyncio.sleep(0.2)

    asyncio.run(run())


def read_media_ingested(queue_name):
    async def read():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True, passive=True)
            bodies = []
            while (message := await queue.get(no_ack=True, fail=False, timeout=2)) is not None:
                bodies.append(json.loads(message.body))
            return bodies

    return asyncio.run(read())


def status_is(session_factory, job_id, *statuses):
    def check():
        with session_factory() as db:
            return db.get(Job, job_id).status in statuses

    return check


def test_worker_events_reach_the_database_and_announce_the_ingestion(queues, session_factory, job, tmp_path, make_sample):
    storage = LocalStorage(tmp_path / "media")
    object_storage = InMemoryObjectStorage()
    job_id, project_id, asset_id = job.id, job.project_id, job.media_asset_id
    object_storage.objects[(str(project_id), "source/lecture.mp4")] = make_sample(tone=True).read_bytes()
    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(JobRequestMessage(
        job_id=job_id,
        project_id=project_id,
        parameters=IngestionParams(media_id=asset_id),
        staged_file="lecture.mp4",
        file_name="lecture.mp4",
    ))

    async def run_worker():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            worker = IngestionWorker(TEST_RABBITMQ_URL, storage, object_storage)
            await worker.open(await connection.channel())
            await worker.process_next()

    asyncio.run(run_worker())
    consume(session_factory, [], status_is(session_factory, job_id, JobStatusEnum.COMPLETED))

    with session_factory() as db:
        assert db.get(MediaAsset, asset_id).status == MediaAssetStatus.READY
    announced = read_media_ingested(queues["MEDIA_INGESTED_QUEUE"])
    assert [event["event"] for event in announced] == ["media.ingested"]
    assert (announced[0]["job_id"], announced[0]["project_id"]) == (str(job_id), str(project_id))
    assert announced[0]["proxy_path"] == "proxy/proxy.mp4"


def test_progress_event_updates_the_job(queues, session_factory, job):
    job_id = job.id

    consume(session_factory, [progress_event(job_id).model_dump_json().encode()], status_is(session_factory, job_id, JobStatusEnum.PROCESSING))

    with session_factory() as db:
        stored = db.get(Job, job_id)
        assert (stored.step, stored.step_progress) == (JobStepProcessingEnum.INSPECTING_MEDIA, 50.0)
    assert read_media_ingested(queues["MEDIA_INGESTED_QUEUE"]) == []


def test_applied_event_is_handed_to_the_clients_watching(queues, session_factory, job):
    job_id, project_id = job.id, job.project_id
    hub = JobProgressHub()

    with hub.watch(project_id) as updates:
        consume(session_factory, [progress_event(job_id).model_dump_json().encode()], status_is(session_factory, job_id, JobStatusEnum.PROCESSING), hub)

        update = updates.get_nowait()
    assert (update.job_id, update.status, update.step_progress) == (job_id, JobStatusEnum.PROCESSING, 50.0)


def test_failed_job_announces_nothing(queues, session_factory, job):
    job_id = job.id
    progress = progress_event(job_id)  # created first: the state machine ignores events older than the last one
    failed = JobUpdateEventSchema(
        job_id=job_id, status=JobStatusEnum.FAILED, step_progress=0, error_code=JobErrorCodeEnum.SILENT_AUDIO, error_message="silent"
    )
    events = [progress.model_dump_json().encode(), failed.model_dump_json().encode()]

    consume(session_factory, events, status_is(session_factory, job_id, JobStatusEnum.FAILED))

    assert read_media_ingested(queues["MEDIA_INGESTED_QUEUE"]) == []


def test_invalid_and_unknown_events_do_not_stop_the_consumer(queues, session_factory, job, caplog):
    job_id = job.id
    events = [b"not an event", progress_event(uuid.uuid4()).model_dump_json().encode(), progress_event(job_id).model_dump_json().encode()]

    with caplog.at_level(logging.WARNING):
        consume(session_factory, events, status_is(session_factory, job_id, JobStatusEnum.PROCESSING))

    assert "Invalid job event" in caplog.text
    assert "unknown job" in caplog.text


def test_event_is_applied_after_a_database_failure(queues, session_factory, job, monkeypatch):
    job_id = job.id
    real_apply = event_consumer.apply_job_event
    calls = []

    def fail_once(db, event):
        calls.append(event)
        if len(calls) == 1:
            raise OperationalError("SELECT 1", {}, Exception("database restarting"))
        return real_apply(db, event)

    monkeypatch.setattr(event_consumer, "apply_job_event", fail_once)

    consume(session_factory, [progress_event(job_id).model_dump_json().encode()], status_is(session_factory, job_id, JobStatusEnum.PROCESSING))

    assert len(calls) == 2


def test_consumer_keeps_trying_while_the_broker_is_down(monkeypatch, caplog):
    monkeypatch.setattr(event_consumer, "EVENT_CONSUMER_RETRY_SECONDS", 0.01)

    async def run():
        task = asyncio.create_task(JobEventConsumer(UNREACHABLE_URL, None, JobProgressHub()).run())
        await asyncio.sleep(0.3)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())

    assert "cannot reach the broker" in caplog.text
