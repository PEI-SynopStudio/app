import uuid

import pytest
from sqlalchemy import select

from app.core.config import AuditAction, JobErrorCodeEnum, JobStatusEnum, JobTypeEnum, MediaAssetStatus, SourceType
from app.database.models import AuditLog, Job, MediaAsset
from app.schemas.job import TranscriptionParams
from app.services.projects.projects import LicenceNotConfirmedError
from app.services.video.playback import MediaNotReadyError
from app.services.workflow.jobs import (
    TranscriptionAlreadyRunningError,
    create_transcription_job,
    fail_job,
    latest_transcription_job,
    queue_job,
)
from app.services.workflow.submission import submit_transcription
from test_submission import BrokenDispatcher, dispatcher, finished_asset, make_project, storage, submit_url  # noqa: F401


def new_transcription(db, project_id, asset_id):
    return create_transcription_job(db, project_id, TranscriptionParams(media_id=asset_id), asset_id)


def test_a_transcription_job_is_pending_and_audited(db, storage):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)

    job = new_transcription(db, project_id, asset.id)

    assert (job.status, job.job_type, job.media_asset_id) == (JobStatusEnum.PENDING, JobTypeEnum.TRANSCRIPTION, asset.id)
    assert job.parameters["language"] == "pt"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.TRANSCRIPTION_REQUESTED))
    assert entry.details == {"job_id": str(job.id)}


def test_a_transcription_needs_a_confirmed_licence(db, storage):
    project_id = make_project(db, licence=False)
    asset, _ = finished_asset(db, storage, project_id)

    with pytest.raises(LicenceNotConfirmedError):
        new_transcription(db, project_id, asset.id)
    assert db.scalar(select(Job)) is None


def test_a_second_active_transcription_is_refused(db, storage):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    new_transcription(db, project_id, asset.id)

    with pytest.raises(TranscriptionAlreadyRunningError):
        new_transcription(db, project_id, asset.id)


def test_a_failed_transcription_can_be_repeated(db, storage):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    fail_job(db, queue_job(db, new_transcription(db, project_id, asset.id)), JobErrorCodeEnum.MODEL_UNAVAILABLE, "no weights")

    assert new_transcription(db, project_id, asset.id).status == JobStatusEnum.PENDING


def test_submission_sends_the_audio_key_and_the_start_offset(db, storage, dispatcher):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    asset.time_start_seconds = 12.5
    db.commit()

    job = submit_transcription(db, dispatcher, asset)

    [request] = dispatcher.requests
    assert job.status == JobStatusEnum.QUEUED
    assert (request.job_id, request.audio_key, request.time_offset_seconds) == (job.id, "audio/audio.wav", 12.5)
    assert request.parameters.media_id == asset.id


def test_a_video_that_was_not_cut_starts_at_zero(db, storage, dispatcher):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)

    submit_transcription(db, dispatcher, asset)

    assert dispatcher.requests[0].time_offset_seconds == 0.0


def test_a_video_without_normalized_audio_is_not_transcribed(db, dispatcher):
    project_id = make_project(db)
    asset = MediaAsset(
        project_id=uuid.UUID(project_id), source_type=SourceType.UPLOAD, file_name="a.mp4", status=MediaAssetStatus.PROCESSING
    )
    db.add(asset)
    db.commit()

    with pytest.raises(MediaNotReadyError):
        submit_transcription(db, dispatcher, asset)
    assert db.scalar(select(Job)) is None


def test_a_broken_broker_fails_the_transcription(db, storage):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)

    with pytest.raises(ConnectionError):
        submit_transcription(db, BrokenDispatcher(), asset)

    assert db.scalar(select(Job)).status == JobStatusEnum.FAILED


def test_latest_transcription_ignores_other_job_types(db, storage, dispatcher):
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    job = fail_job(db, submit_transcription(db, dispatcher, asset), JobErrorCodeEnum.MODEL_UNAVAILABLE, "no weights")
    submit_url(db, dispatcher, project_id)

    assert latest_transcription_job(db, uuid.UUID(project_id)).id == job.id
