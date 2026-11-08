import shutil
import threading
import uuid
from datetime import date

import pytest

from app.core.config import JobErrorCodeEnum, JobStatusEnum, LicenseType
from app.database.models import Job
from app.schemas.job import IngestionParams, JobRequestMessage, JobUpdateEventSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.storage.local import LocalStorage
from app.services.workflow import dispatcher as dispatcher_module
from app.services.workflow.dispatcher import InProcessDispatcher
from app.services.workflow.jobs import create_ingestion_job, queue_job

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
JOIN_TIMEOUT_SECONDS = 60


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def events():
    return []


@pytest.fixture
def dispatcher(storage, events, session_factory):
    instance = InProcessDispatcher(storage, session_factory, publish_event=events.append)
    yield instance
    instance.join(JOIN_TIMEOUT_SECONDS)


@pytest.fixture
def job(db):
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
    params = IngestionParams(source_url=SAMPLE_URL)
    return queue_job(db, create_ingestion_job(db, str(project.id), params, SAMPLE_URL))


def request_for(job):
    return JobRequestMessage(
        job_id=job.id,
        project_id=job.project_id,
        parameters=IngestionParams(media_id=uuid.uuid4()),
        staged_file="lecture.mp4",
        file_name="lecture.mp4",
    )


def stage(storage, job, sample):
    shutil.copy(sample, storage.path(str(job.project_id), "source", "lecture.mp4"))


def stored_status(db, job):
    db.expire_all()
    return db.get(Job, job.id).status


@pytest.fixture
def blocked_pipeline(monkeypatch):
    """Replace the pipeline with one that waits until the test releases it."""
    started, release = threading.Event(), threading.Event()

    def fake_run_ingestion(storage, request, emit):
        started.set()
        release.wait(JOIN_TIMEOUT_SECONDS)
        return JobUpdateEventSchema(
            job_id=request.job_id,
            status=JobStatusEnum.FAILED,
            step_progress=0,
            error_code=JobErrorCodeEnum.INTERNAL_ERROR,
        )

    monkeypatch.setattr(dispatcher_module, "run_ingestion", fake_run_ingestion)
    return started, release


def test_dispatch_runs_job_and_publishes_event(dispatcher, storage, db, job, events, make_sample):
    stage(storage, job, make_sample(tone=True))

    dispatcher.dispatch(request_for(job))
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert stored_status(db, job) == JobStatusEnum.COMPLETED
    assert len(events) == 1
    event = events[0]
    assert (event.event, event.job_id, event.project_id) == ("media.ingested", job.id, job.project_id)
    assert (event.audio_path, event.proxy_path) == ("audio/audio.wav", "proxy/proxy.mp4")


def test_dispatch_returns_before_the_job_ends(dispatcher, db, job, blocked_pipeline):
    started, release = blocked_pipeline

    dispatcher.dispatch(request_for(job))

    assert started.wait(JOIN_TIMEOUT_SECONDS)
    assert stored_status(db, job) == JobStatusEnum.QUEUED
    release.set()


def test_failed_ingestion_publishes_no_event(dispatcher, storage, db, job, events, make_sample):
    stage(storage, job, make_sample())  # silent audio

    dispatcher.dispatch(request_for(job))
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert stored_status(db, job) == JobStatusEnum.FAILED
    assert events == []


def test_crashed_job_is_logged(dispatcher, job, monkeypatch, caplog):
    def crash(*args, **kwargs):
        raise KeyError("bug")

    monkeypatch.setattr(dispatcher_module, "run_ingestion", crash)

    dispatcher.dispatch(request_for(job))
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert "Ingestion job crashed" in caplog.text
