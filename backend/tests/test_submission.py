import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import JobStatusEnum, LicenseType, MediaAssetStatus, ProjectStatus, SourceType
from app.database.models import AudioTrack, Job, MediaAsset, Project, UploadSession
from app.schemas.project import ProjectCreate
from app.services.projects.projects import LicenceNotConfirmedError, create_project
from app.services.storage.local import LocalStorage
from app.services.video.uploads import start_upload
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.jobs import IngestionAlreadyRunningError
from app.services.workflow.submission import submit_upload_ingestion, submit_url_ingestion

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"


class RecordingDispatcher(JobDispatcher):
    def __init__(self):
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)


class BrokenDispatcher(JobDispatcher):
    def dispatch(self, request):
        raise ConnectionError("broker down")


@pytest.fixture
def dispatcher():
    return RecordingDispatcher()


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


def make_project(db, licence=True):
    return str(create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=licence,
        authorship_confirmed=True,
    )).id)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def submit_url(db, dispatcher, project_id, start=None, end=None, storage=None):
    storage = storage or LocalStorage(Path(tempfile.gettempdir()) / "unused-media")
    return submit_url_ingestion(db, storage, dispatcher, project_id, SAMPLE_URL, start, end)


def test_url_submission_creates_the_asset_and_queues_the_job(db, dispatcher):
    job = submit_url(db, dispatcher, make_project(db), "00:01:00", "00:02:00")

    assert job.status == JobStatusEnum.QUEUED
    asset = db.get(MediaAsset, job.media_asset_id)
    assert (asset.source_url, asset.status) == (SAMPLE_URL, MediaAssetStatus.PROCESSING)
    assert (asset.time_start_seconds, asset.time_end_seconds) == (60, 120)
    request = dispatcher.requests[0]
    assert (request.job_id, request.project_id) == (job.id, job.project_id)
    assert str(request.parameters.source_url) == SAMPLE_URL


def test_url_submission_accepts_an_open_ended_range(db, dispatcher):
    job = submit_url(db, dispatcher, make_project(db), "00:01:00")

    asset = db.get(MediaAsset, job.media_asset_id)
    assert (asset.time_start_seconds, asset.time_end_seconds) == (60, None)


def test_url_without_licence_creates_nothing(db, dispatcher):
    project_id = make_project(db, licence=False)

    with pytest.raises(LicenceNotConfirmedError):
        submit_url(db, dispatcher, project_id)

    assert (count(db, MediaAsset), count(db, Job), dispatcher.requests) == (0, 0, [])


def test_refused_url_leaves_no_new_asset(db, dispatcher):
    project_id = make_project(db)
    submit_url(db, dispatcher, project_id)

    with pytest.raises(IngestionAlreadyRunningError):
        submit_url(db, dispatcher, project_id)

    assert (count(db, MediaAsset), len(dispatcher.requests)) == (1, 1)


def test_upload_submission_closes_the_session(db, storage, dispatcher):
    session = start_upload(db, make_project(db), "Debate.mp4", 10, "video/mp4")
    upload_id, staged_file = session.id, session.staged_file

    job = submit_upload_ingestion(db, storage, dispatcher, session)

    assert job.status == JobStatusEnum.QUEUED
    assert count(db, UploadSession) == 0
    assert db.get(MediaAsset, job.media_asset_id).status == MediaAssetStatus.PROCESSING
    request = dispatcher.requests[0]
    assert (request.upload_id, request.staged_file, request.file_name) == (upload_id, staged_file, "Debate.mp4")
    assert request.parameters.media_id == job.media_asset_id
    assert db.get(MediaAsset, job.media_asset_id).source_key == f"source/{staged_file}"


def test_upload_submission_records_the_requested_range(db, storage, dispatcher):
    session = start_upload(db, make_project(db), "Debate.mp4", 10, "video/mp4")

    job = submit_upload_ingestion(db, storage, dispatcher, session, "00:01:00", "00:02:00")

    asset = db.get(MediaAsset, job.media_asset_id)
    assert (asset.time_start_seconds, asset.time_end_seconds) == (60, 120)
    assert (dispatcher.requests[0].parameters.time_start, dispatcher.requests[0].parameters.time_end) == ("00:01:00", "00:02:00")


def test_upload_survives_a_broker_failure_and_can_be_completed_again(db, storage, dispatcher):
    session = start_upload(db, make_project(db), "Debate.mp4", 10, "video/mp4")
    session_id = session.id

    with pytest.raises(ConnectionError):
        submit_upload_ingestion(db, storage, BrokenDispatcher(), session)

    retried = db.get(UploadSession, session_id)
    assert retried is not None
    job = submit_upload_ingestion(db, storage, dispatcher, retried)
    assert job.status == JobStatusEnum.QUEUED
    assert count(db, UploadSession) == 0
    assert db.get(MediaAsset, job.media_asset_id).status == MediaAssetStatus.PROCESSING


def test_refused_upload_keeps_the_session(db, storage, dispatcher):
    project_id = make_project(db)
    submit_url(db, dispatcher, project_id)
    session = start_upload(db, project_id, "Debate.mp4", 10, "video/mp4")

    with pytest.raises(IngestionAlreadyRunningError):
        submit_upload_ingestion(db, storage, dispatcher, session)

    assert db.get(UploadSession, uuid.UUID(str(session.id))) is not None


def test_a_broken_broker_fails_the_job(db):
    project_id = make_project(db)

    with pytest.raises(ConnectionError):
        submit_url(db, BrokenDispatcher(), project_id)

    job = db.scalar(select(Job))
    assert (job.status, job.error_message) == (JobStatusEnum.FAILED, "The job could not be queued; please try again.")
    assert db.get(Project, uuid.UUID(project_id)).status == ProjectStatus.INGESTION_FAILED


def finished_asset(db, storage, project_id, status=MediaAssetStatus.READY):
    """A previous video of the project, with its files on disk."""
    asset = MediaAsset(
        project_id=uuid.UUID(project_id),
        source_type=SourceType.UPLOAD,
        file_name="old.mp4",
        status=status,
        source_key="source/old.mp4",
        proxy_key="proxy/proxy.mp4",
        keyframes_key="analysis/keyframes.json",
    )
    db.add(asset)
    db.flush()
    db.add(AudioTrack(
        media_asset_id=asset.id,
        sample_rate=16000,
        channels=1,
        format="wav",
        storage_key="audio/audio.wav",
        waveform_key="analysis/waveform.json",
    ))
    db.commit()
    keys = ("source/old.mp4", "proxy/proxy.mp4", "audio/audio.wav", "analysis/waveform.json", "analysis/keyframes.json")
    files = [storage.path(project_id, key) for key in keys]
    for file in files:
        file.write_bytes(b"old")
    return asset, files


@pytest.mark.parametrize("status", [MediaAssetStatus.READY, MediaAssetStatus.FAILED])
def test_a_new_ingestion_replaces_the_previous_video(db, storage, dispatcher, status):
    project_id = make_project(db)
    previous, files = finished_asset(db, storage, project_id, status)
    previous_id = previous.id

    job = submit_url(db, dispatcher, project_id, storage=storage)

    db.expire_all()
    assert db.get(MediaAsset, previous_id) is None
    assert db.get(MediaAsset, job.media_asset_id) is not None
    assert count(db, AudioTrack) == 0
    assert not any(file.exists() for file in files)


def test_an_upload_in_progress_is_not_replaced(db, storage, dispatcher):
    project_id = make_project(db)
    start_upload(db, project_id, "Debate.mp4", 10, "video/mp4")

    submit_url(db, dispatcher, project_id, storage=storage)

    assert count(db, MediaAsset) == 2
    assert count(db, UploadSession) == 1


def test_a_refused_ingestion_keeps_the_previous_video(db, storage, dispatcher):
    project_id = make_project(db)
    submit_url(db, dispatcher, project_id, storage=storage)
    _, files = finished_asset(db, storage, project_id)

    with pytest.raises(IngestionAlreadyRunningError):
        submit_url(db, dispatcher, project_id, storage=storage)

    assert all(file.exists() for file in files)
