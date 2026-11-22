import asyncio
import uuid
from datetime import datetime, timezone

import aio_pika
import pytest
from fastapi.testclient import TestClient

from app.core.config import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.database.models import Job
from app.main import app
from app.schemas.job import JobUpdateEventSchema
from app.services.storage.local import get_storage
from app.services.storage.object_storage import get_object_storage
from app.services.workflow import rabbitmq as rabbitmq_module
from app.services.workflow.progress_hub import JobProgressHub, get_progress_hub
from app.services.workflow.rabbitmq import RabbitMQDispatcher, get_dispatcher
from app.workers import ingestion_worker
from app.workers.ingestion_worker import IngestionWorker
from test_api_uploads import new_project
from test_event_consumer import consume, read_media_ingested, status_is
from test_rabbitmq import TEST_RABBITMQ_URL

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
# The completed event of an ingestion must carry its output; the values do not matter here.
OUTPUT = {
    "source_type": "url",
    "source": SAMPLE_URL,
    "container": "mp4",
    "size_bytes": 1000,
    "video_codec": "h264",
    "audio_codec": "aac",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source_key": "source/download.mp4",
    "proxy_key": "proxy/proxy.mp4",
    "audio_key": "audio/audio.wav",
    "waveform_key": "audio/waveform.json",
    "keyframes_key": "proxy/keyframes.json",
}


def processing(job_id, step, percent):
    return JobUpdateEventSchema(job_id=job_id, status=JobStatusEnum.PROCESSING, step=step, step_progress=percent)


def completed(job_id):
    return JobUpdateEventSchema(job_id=job_id, status=JobStatusEnum.COMPLETED, step_progress=100, output=OUTPUT)


def failed(job_id):
    return JobUpdateEventSchema(
        job_id=job_id, status=JobStatusEnum.FAILED, step_progress=0,
        error_code=JobErrorCodeEnum.SILENT_AUDIO, error_message="silent",
    )


def successful_run(job_id):
    return [
        processing(job_id, JobStepProcessingEnum.INSPECTING_MEDIA, 100),
        processing(job_id, JobStepProcessingEnum.GENERATING_PROXY, 50),
        completed(job_id),
    ]


def failed_run(job_id):
    return [processing(job_id, JobStepProcessingEnum.INSPECTING_MEDIA, 50), failed(job_id)]


@pytest.fixture
def stack(queues, db_override):
    """The API wired to the real broker and the test queues.

    The client is not entered, so the lifespan does not start a consumer on the development broker.
    """
    hub = JobProgressHub()
    app.dependency_overrides[get_storage] = lambda: None
    app.dependency_overrides[get_object_storage] = lambda: None
    app.dependency_overrides[get_dispatcher] = lambda: RabbitMQDispatcher(TEST_RABBITMQ_URL)
    app.dependency_overrides[get_progress_hub] = lambda: hub
    yield TestClient(app), hub
    app.dependency_overrides.clear()


@pytest.fixture
def scripted_pipeline(monkeypatch):
    """Replace the media pipeline of the worker: each job only emits the events given for it."""
    runs = {}

    def run(storage, object_storage, request, emit):
        for event in runs.get(str(request.job_id), lambda job_id: [])(request.job_id):
            emit(event)

    monkeypatch.setattr(ingestion_worker, "run_ingestion", run)
    return runs


def submit(client, project_id=None):
    """Queue a job through the API; returns (project_id, job_id)."""
    project_id = project_id or new_project(client)
    accepted = client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    return project_id, accepted.json()["job_id"]


def run_worker(jobs=1):
    """Let the worker take the next `jobs` messages from the queue."""

    async def run():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            worker = IngestionWorker(TEST_RABBITMQ_URL, None, None)
            await worker.open(await connection.channel())
            for _ in range(jobs):
                assert await worker.process_next()

    asyncio.run(run())


def read_bodies(queue_name):
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


def job_state(client, project_id, job_id):
    response = client.get(f"/projects/{project_id}/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


def test_job_goes_from_the_api_to_completed_through_the_broker(stack, scripted_pipeline, session_factory, queues):
    """T3.13: API → queued → broker → worker → events → consumer → completed, seen through the API and the hub."""
    client, hub = stack
    project_id, job_id = submit(client)
    scripted_pipeline[job_id] = successful_run
    assert job_state(client, project_id, job_id)["status"] == "queued"

    run_worker()
    with hub.watch(uuid.UUID(project_id)) as updates:
        consume(session_factory, [], status_is(session_factory, uuid.UUID(job_id), JobStatusEnum.COMPLETED), hub)
        latest_update = updates.get_nowait()

    state = job_state(client, project_id, job_id)
    assert (state["status"], state["step"], state["progress"]) == ("completed", "finished", 100.0)
    assert state["started_at"] is not None and state["finished_at"] is not None
    assert latest_update.status == JobStatusEnum.COMPLETED
    assert [job["job_id"] for job in client.get(f"/projects/{project_id}/jobs").json()] == [job_id]
    announced = read_media_ingested(queues["MEDIA_INGESTED_QUEUE"])
    assert [(event["event"], event["job_id"]) for event in announced] == [("media.ingested", job_id)]


def test_failed_job_keeps_its_error_and_frees_the_project(stack, scripted_pipeline, session_factory, queues):
    client, _ = stack
    project_id, job_id = submit(client)
    scripted_pipeline[job_id] = failed_run

    run_worker()
    consume(session_factory, [], status_is(session_factory, uuid.UUID(job_id), JobStatusEnum.FAILED))

    state = job_state(client, project_id, job_id)
    assert (state["status"], state["error_code"], state["error_message"]) == ("failed", "silent_audio", "silent")
    assert read_media_ingested(queues["MEDIA_INGESTED_QUEUE"]) == []


def test_cancelled_job_ignores_the_worker_events(stack, scripted_pipeline, session_factory, db, queues):
    """The worker does not know about the cancellation; its events arrive late and change nothing."""
    client, _ = stack
    project_id, job_id = submit(client)
    scripted_pipeline[job_id] = successful_run

    cancelled = client.post(f"/projects/{project_id}/jobs/{job_id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    run_worker()

    # Consumed after the worker's events (prefetch 1 keeps the order), so all of them have been handled.
    marker = Job(
        project_id=uuid.UUID(project_id),
        job_type=JobTypeEnum.TRANSCRIPTION,
        status=JobStatusEnum.QUEUED,
        parameters={"job_type": "transcription", "media_id": str(uuid.uuid4()), "language": "pt"},
    )
    db.add(marker)
    db.commit()
    marker_event = processing(marker.id, JobStepProcessingEnum.TRANSCRIBING, 10)
    consume(
        session_factory,
        [marker_event.model_dump_json().encode()],
        status_is(session_factory, marker.id, JobStatusEnum.PROCESSING),
    )

    state = job_state(client, project_id, job_id)
    assert (state["status"], state["output"]) == ("cancelled", None)
    assert read_media_ingested(queues["MEDIA_INGESTED_QUEUE"]) == []


def test_invalid_job_request_goes_to_the_dead_letter_queue(stack, scripted_pipeline, session_factory, queues):
    """A broken request is kept in the DLQ and the worker still processes the next job."""
    client, _ = stack

    async def publish_garbage():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            exchange, _ = await rabbitmq_module.declare_job_queue(await connection.channel(), JobTypeEnum.INGESTION.value)
            await exchange.publish(aio_pika.Message(body=b"not a job"), JobTypeEnum.INGESTION.value)

    asyncio.run(publish_garbage())
    project_id, job_id = submit(client)
    scripted_pipeline[job_id] = successful_run

    run_worker(jobs=2)
    consume(session_factory, [], status_is(session_factory, uuid.UUID(job_id), JobStatusEnum.COMPLETED))

    assert job_state(client, project_id, job_id)["status"] == "completed"
    assert read_bodies(queues["DEAD_LETTER_QUEUE"]) == [b"not a job"]
