import asyncio
import uuid

import aio_pika
import pytest

from app.core.config import JobStatusEnum
from app.schemas.job import IngestionParams, JobRequestMessage, TranscriptionParams
from app.services.speech.models import LoadedAligner, LoadedWhisper
from app.services.storage.local import LocalStorage
from app.services.workflow import rabbitmq as rabbitmq_module
from app.services.workflow.rabbitmq import RabbitMQDispatcher
from app.services.workflow.transcription_pipeline import SpeechModels
from app.workers import speech_worker
from app.workers.speech_worker import SpeechWorker
from in_memory_object_storage import InMemoryObjectStorage
from test_ingestion_worker import events_in, read_all
from test_rabbitmq import TEST_RABBITMQ_URL, broker_is_running
from test_speech_audio import write_wav
from test_speech_transcription import FakeWhisper, spoken
from test_transcription_pipeline import aligned_as_whisper  # noqa: F401


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def models():
    return SpeechModels(
        LoadedWhisper("large-v3-turbo", "a" * 40, FakeWhisper([spoken(" Bom dia.", 0.5, 1.5)])),
        lambda language: LoadedAligner("wav2vec2-pt", "b" * 40, None, None),
    )


@pytest.fixture
def queues(monkeypatch):
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
    job_queues = [names["JOBS_QUEUE_FORMAT"].format(job_type=job_type) for job_type in ("transcription", "ingestion")]
    yield job_queues, names["JOB_EVENTS_QUEUE"]

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            for queue in (*job_queues, names["JOB_EVENTS_QUEUE"]):
                await channel.queue_delete(queue)
            await channel.exchange_delete(names["JOBS_EXCHANGE"])
            await channel.exchange_delete(names["JOB_EVENTS_EXCHANGE"])

    asyncio.run(remove())


def process_next(storage, object_storage, models):
    async def run():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            worker = SpeechWorker(TEST_RABBITMQ_URL, storage, object_storage, models)
            await worker.open(await connection.channel())
            return await worker.process_next()

    return asyncio.run(run())


def transcription_request(tmp_path, object_storage):
    project_id = uuid.uuid4()
    wav = tmp_path / "audio.wav"
    write_wav(wav, [(3, 0.5)])
    object_storage.put_file(str(project_id), "audio/audio.wav", wav)
    return JobRequestMessage(
        job_id=uuid.uuid4(),
        project_id=project_id,
        parameters=TranscriptionParams(media_id=uuid.uuid4()),
        audio_key="audio/audio.wav",
    )


def test_job_runs_with_the_models_loaded_at_start(storage, models, monkeypatch):
    calls = []
    monkeypatch.setattr(speech_worker, "run_transcription", lambda *args: calls.append(args))
    worker = SpeechWorker(TEST_RABBITMQ_URL, storage, InMemoryObjectStorage(), models)
    request = JobRequestMessage(job_id=uuid.uuid4(), project_id=uuid.uuid4(), parameters=TranscriptionParams(media_id=uuid.uuid4()))

    worker.run_job(request)

    [(_, _, used_models, used_request, emit)] = calls
    assert (used_models, used_request, emit) == (models, request, worker._emit)


def test_main_loads_the_models_before_reading_the_queue(monkeypatch):
    order = []
    monkeypatch.setattr(speech_worker, "load_whisper", lambda: order.append("whisper"))
    monkeypatch.setattr(speech_worker, "load_aligner", lambda language: order.append(f"aligner:{language}"))
    monkeypatch.setattr(speech_worker, "get_object_storage", lambda: None)

    async def fake_run(self):
        order.append("queue")

    monkeypatch.setattr(SpeechWorker, "run", fake_run)

    speech_worker.main()

    assert order == ["whisper", "aligner:pt", "queue"]


def test_worker_transcribes_the_job_and_publishes_its_events(queues, storage, models, tmp_path):
    _, events_queue = queues
    object_storage = InMemoryObjectStorage()
    request = transcription_request(tmp_path, object_storage)
    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(request)

    assert process_next(storage, object_storage, models) is True

    events = events_in(events_queue)
    assert {event.job_id for event in events} == {request.job_id}
    assert events[-1].status == JobStatusEnum.COMPLETED, events[-1].error_message
    assert (str(request.project_id), "transcript/transcript.json") in object_storage.objects


def test_worker_only_takes_transcription_jobs(queues, storage, models):
    (_, ingestion_queue), _ = queues
    RabbitMQDispatcher(TEST_RABBITMQ_URL).dispatch(
        JobRequestMessage(job_id=uuid.uuid4(), project_id=uuid.uuid4(), parameters=IngestionParams(media_id=uuid.uuid4()))
    )

    assert process_next(storage, InMemoryObjectStorage(), models) is False
    assert len(read_all(ingestion_queue)) == 1
