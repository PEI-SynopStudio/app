import shutil
import threading
import uuid
from datetime import date

import pytest

from app.core.config import IngestionStage, LicenseType, SourceType
from app.schemas.project import ProjectCreate
from app.services.projects.projects import LicenceNotConfirmedError, ProjectNotFoundError, create_project
from app.services.storage.local import LocalStorage
from app.services.workflow import dispatcher as dispatcher_module
from app.services.workflow.dispatcher import IngestionAlreadyRunningError, InProcessDispatcher
from app.services.workflow.ingestion_pipeline import IngestionJob
from app.services.workflow.status import get_status, set_stage

JOIN_TIMEOUT_SECONDS = 60


def make_project(db, authorship=True):
    return str(create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=authorship,
    )).id)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def project_id(db):
    return make_project(db)


@pytest.fixture
def events():
    return []


@pytest.fixture
def dispatcher(storage, events, session_factory):
    instance = InProcessDispatcher(storage, session_factory, publish_event=events.append)
    yield instance
    instance.join(JOIN_TIMEOUT_SECONDS)


def upload_job(storage, project_id, sample):
    shutil.copy(sample, storage.path(project_id, "source", "lecture.mp4"))
    return IngestionJob(
        project_id=project_id, source_type=SourceType.UPLOAD, source="lecture.mp4", staged_file="lecture.mp4"
    )


@pytest.fixture
def blocked_pipeline(monkeypatch):
    """Replace the pipeline with one that waits until the test releases it."""
    started, release = threading.Event(), threading.Event()

    def fake_run_ingestion(storage, job, on_progress=None):
        started.set()
        release.wait(JOIN_TIMEOUT_SECONDS)
        return set_stage(storage, job.project_id, IngestionStage.COMPLETED)

    monkeypatch.setattr(dispatcher_module, "run_ingestion", fake_run_ingestion)
    return started, release


def test_dispatch_runs_job_and_publishes_event(dispatcher, storage, project_id, events, make_sample):
    queued = dispatcher.dispatch(upload_job(storage, project_id, make_sample(tone=True)))
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert queued.stage == IngestionStage.QUEUED
    assert get_status(storage, project_id).stage == IngestionStage.COMPLETED
    assert len(events) == 1
    event = events[0]
    assert (event.event, event.project_id) == ("media.ingested", project_id)
    assert (event.audio_path, event.proxy_path, event.metadata_path) == (
        "audio/audio.wav", "proxy/proxy.mp4", "metadata.json"
    )


def test_dispatch_returns_before_the_job_ends(dispatcher, storage, project_id, blocked_pipeline):
    started, release = blocked_pipeline

    status = dispatcher.dispatch(IngestionJob(project_id=project_id, source_type=SourceType.URL, source="x"))

    assert started.wait(JOIN_TIMEOUT_SECONDS)
    assert status.stage == IngestionStage.QUEUED
    assert dispatcher.is_running(project_id)
    release.set()


def test_second_job_for_same_project_is_refused(dispatcher, storage, project_id, blocked_pipeline):
    _, release = blocked_pipeline
    job = IngestionJob(project_id=project_id, source_type=SourceType.URL, source="x")
    dispatcher.dispatch(job)

    with pytest.raises(IngestionAlreadyRunningError):
        dispatcher.dispatch(job)

    release.set()
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    assert dispatcher.dispatch(job).stage == IngestionStage.QUEUED


def test_failed_ingestion_publishes_no_event(dispatcher, storage, project_id, events, make_sample):
    dispatcher.dispatch(upload_job(storage, project_id, make_sample()))  # silent audio
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert get_status(storage, project_id).stage == IngestionStage.FAILED
    assert events == []


def test_dispatch_refuses_without_licence(dispatcher, storage, db):
    project_id = make_project(db, authorship=False)

    with pytest.raises(LicenceNotConfirmedError):
        dispatcher.dispatch(IngestionJob(project_id=project_id, source_type=SourceType.URL, source="x"))
    assert get_status(storage, project_id) is None


def test_dispatch_refuses_unknown_project(dispatcher):
    with pytest.raises(ProjectNotFoundError):
        dispatcher.dispatch(IngestionJob(project_id=str(uuid.uuid4()), source_type=SourceType.URL, source="x"))


def test_crashed_job_is_logged_and_frees_the_project(dispatcher, storage, project_id, monkeypatch, caplog):
    def crash(*args, **kwargs):
        raise KeyError("bug")

    monkeypatch.setattr(dispatcher_module, "run_ingestion", crash)
    job = IngestionJob(project_id=project_id, source_type=SourceType.URL, source="x")

    dispatcher.dispatch(job)
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    assert "Ingestion job crashed" in caplog.text
    assert not dispatcher.is_running(project_id)
