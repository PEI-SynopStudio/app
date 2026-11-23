import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

import aio_pika
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import JobStatusEnum, JobTypeEnum, MediaAssetStatus, SourceType
from app.database.models import Job, MediaAsset
from app.schemas.job import IngestionParams
from app.services.workflow import rabbitmq as rabbitmq_module, transcription_trigger
from app.services.workflow.event_consumer import MediaIngestedEvent
from app.services.workflow.jobs import create_ingestion_job
from app.services.workflow.transcription_trigger import TranscriptionTrigger
from test_rabbitmq import TEST_RABBITMQ_URL, broker_is_running
from test_submission import RecordingDispatcher, dispatcher, finished_asset, make_project, storage  # noqa: F401

WAIT_SECONDS = 20


def ingested(db, project_id, asset_id):
    job = create_ingestion_job(db, project_id, IngestionParams(media_id=asset_id), "old.mp4", media_asset_id=asset_id)
    return MediaIngestedEvent(
        job_id=job.id,
        project_id=uuid.UUID(project_id),
        audio_path="audio/audio.wav",
        proxy_path="proxy/proxy.mp4",
        occurred_at=datetime.now(timezone.utc),
    )


def transcriptions(db):
    return db.scalars(select(Job).where(Job.job_type == JobTypeEnum.TRANSCRIPTION)).all()


@pytest.fixture
def trigger(session_factory, dispatcher):
    return TranscriptionTrigger(TEST_RABBITMQ_URL, session_factory, dispatcher)


def test_an_ingested_video_is_transcribed(db, storage, dispatcher, trigger):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)

    trigger.start_transcription(ingested(db, project_id, asset.id))

    [job] = transcriptions(db)
    assert (job.status, job.media_asset_id) == (JobStatusEnum.QUEUED, asset.id)
    assert dispatcher.requests[0].audio_key == "audio/audio.wav"


def test_a_repeated_event_starts_one_transcription(db, storage, dispatcher, trigger):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    event = ingested(db, project_id, asset.id)

    trigger.start_transcription(event)
    trigger.start_transcription(event)

    assert len(transcriptions(db)) == 1
    assert len(dispatcher.requests) == 1


def test_a_failed_transcription_is_not_started_again_by_the_same_event(db, storage, dispatcher, trigger):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    event = ingested(db, project_id, asset.id)
    trigger.start_transcription(event)
    db.expire_all()
    transcriptions(db)[0].status = JobStatusEnum.FAILED
    db.commit()

    trigger.start_transcription(event)

    assert len(transcriptions(db)) == 1


def test_a_project_without_licence_is_not_transcribed(db, storage, dispatcher, trigger, caplog):
    project_id = make_project(db, licence=False)
    asset, _ = finished_asset(db, storage, project_id)
    job = Job(project_id=uuid.UUID(project_id), media_asset_id=asset.id, job_type=JobTypeEnum.INGESTION, parameters={})
    db.add(job)
    db.commit()
    event = MediaIngestedEvent(
        job_id=job.id, project_id=uuid.UUID(project_id), audio_path="a", proxy_path="p", occurred_at=datetime.now(timezone.utc)
    )

    with caplog.at_level(logging.WARNING):
        trigger.start_transcription(event)

    assert transcriptions(db) == []
    assert "not started" in caplog.text


def test_an_event_for_a_video_that_is_gone_starts_nothing(db, dispatcher, trigger, caplog):
    event = MediaIngestedEvent(
        job_id=uuid.uuid4(), project_id=uuid.uuid4(), audio_path="a", proxy_path="p", occurred_at=datetime.now(timezone.utc)
    )

    with caplog.at_level(logging.WARNING):
        trigger.start_transcription(event)

    assert transcriptions(db) == []
    assert "no video left" in caplog.text


def test_a_video_without_normalized_audio_is_not_transcribed(db, dispatcher, trigger):
    project_id = make_project(db)
    asset = MediaAsset(project_id=uuid.UUID(project_id), source_type=SourceType.UPLOAD, file_name="a.mp4", status=MediaAssetStatus.READY)
    db.add(asset)
    db.commit()

    trigger.start_transcription(ingested(db, project_id, asset.id))

    assert transcriptions(db) == []


@pytest.fixture
def media_queue(monkeypatch):
    if not broker_is_running():
        pytest.skip("RabbitMQ is not available; run 'docker compose up -d rabbitmq' first")
    prefix = f"test-{uuid.uuid4().hex}"
    names = {"MEDIA_EVENTS_EXCHANGE": f"{prefix}-media", "MEDIA_INGESTED_QUEUE": f"{prefix}-media.ingested"}
    for constant, value in names.items():
        monkeypatch.setattr(rabbitmq_module, constant, value)
    monkeypatch.setattr(transcription_trigger, "EVENT_CONSUMER_RETRY_SECONDS", 0.05)
    yield names

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            await channel.queue_delete(names["MEDIA_INGESTED_QUEUE"])
            await channel.exchange_delete(names["MEDIA_EVENTS_EXCHANGE"])

    asyncio.run(remove())


def deliver(trigger, bodies, done):

    async def run():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            await trigger.open(await connection.channel())
            exchange = await rabbitmq_module.declare_media_events_exchange(await connection.channel())
            for body in bodies:
                await exchange.publish(aio_pika.Message(body=body), rabbitmq_module.MEDIA_INGESTED_EVENT)
            deadline = time.monotonic() + WAIT_SECONDS
            while not await asyncio.to_thread(done):
                assert time.monotonic() < deadline, "the trigger did not finish in time"
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)

    asyncio.run(run())


def has_transcription(session_factory):
    def check():
        with session_factory() as db:
            return bool(transcriptions(db))

    return check


def test_media_ingested_from_the_broker_starts_the_transcription(media_queue, db, storage, session_factory, trigger, caplog):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    event = ingested(db, project_id, asset.id)

    with caplog.at_level(logging.ERROR):
        deliver(trigger, [b"not an event", event.model_dump_json().encode()], has_transcription(session_factory))

    assert "Invalid media event" in caplog.text


def test_media_event_is_handled_after_a_database_failure(media_queue, db, storage, session_factory, trigger, monkeypatch):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    event = ingested(db, project_id, asset.id)
    real_start = trigger.start_transcription
    calls = []

    def fail_once(received):
        calls.append(received)
        if len(calls) == 1:
            raise OperationalError("SELECT 1", {}, Exception("database restarting"))
        return real_start(received)

    monkeypatch.setattr(trigger, "start_transcription", fail_once)

    deliver(trigger, [event.model_dump_json().encode()], has_transcription(session_factory))

    assert len(calls) == 2
