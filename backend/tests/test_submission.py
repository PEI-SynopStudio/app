import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.config import JobStatusEnum, LicenseType, MediaAssetStatus, ProjectStatus
from app.database.models import Job, MediaAsset, Project, UploadSession
from app.schemas.project import ProjectCreate
from app.services.projects.projects import LicenceNotConfirmedError, create_project
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


def submit_url(db, dispatcher, project_id, start=None, end=None):
    return submit_url_ingestion(db, dispatcher, project_id, SAMPLE_URL, start, end)


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


def test_upload_submission_closes_the_session(db, dispatcher):
    session = start_upload(db, make_project(db), "Debate.mp4", 10, "video/mp4")
    upload_id, staged_file = session.id, session.staged_file

    job = submit_upload_ingestion(db, dispatcher, session)

    assert job.status == JobStatusEnum.QUEUED
    assert count(db, UploadSession) == 0
    assert db.get(MediaAsset, job.media_asset_id).status == MediaAssetStatus.PROCESSING
    request = dispatcher.requests[0]
    assert (request.upload_id, request.staged_file, request.file_name) == (upload_id, staged_file, "Debate.mp4")
    assert request.parameters.media_id == job.media_asset_id


def test_refused_upload_keeps_the_session(db, dispatcher):
    project_id = make_project(db)
    submit_url(db, dispatcher, project_id)
    session = start_upload(db, project_id, "Debate.mp4", 10, "video/mp4")

    with pytest.raises(IngestionAlreadyRunningError):
        submit_upload_ingestion(db, dispatcher, session)

    assert db.get(UploadSession, uuid.UUID(str(session.id))) is not None


def test_a_broken_broker_fails_the_job(db):
    project_id = make_project(db)

    with pytest.raises(ConnectionError):
        submit_url(db, BrokenDispatcher(), project_id)

    job = db.scalar(select(Job))
    assert (job.status, job.error_message) == (JobStatusEnum.FAILED, "The job could not be queued; please try again.")
    assert db.get(Project, uuid.UUID(project_id)).status == ProjectStatus.INGESTION_FAILED
