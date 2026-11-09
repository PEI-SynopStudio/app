import asyncio
import logging
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.config import (
    ApplyOutcome,
    AuditAction,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    LicenseType,
    MediaAssetStatus,
    ProjectStatus,
    SourceType,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import AuditLog, Job, MediaAsset, Project, UploadSession
from app.schemas.job import IngestionParams, JobUpdateEventSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.storage.local import LocalStorage
from app.services.video.uploads import purge_expired_uploads, start_upload
from app.services.workflow import sweeper
from app.services.workflow.jobs import apply_job_event, create_ingestion_job, queue_job, sweep_stalled_jobs
from app.services.workflow.progress_hub import JobProgressHub
from app.services.workflow.sweeper import run_periodic_sweep, sweep_once

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
TWO_HOURS = timedelta(hours=2)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


def make_project(db):
    return str(create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    )).id)


def queued_job(db):
    project_id = make_project(db)
    asset = MediaAsset(project_id=uuid.UUID(project_id), source_type=SourceType.URL, source_url=SAMPLE_URL, status=MediaAssetStatus.PROCESSING)
    db.add(asset)
    db.commit()
    return queue_job(db, create_ingestion_job(db, project_id, IngestionParams(source_url=SAMPLE_URL), SAMPLE_URL, media_asset_id=asset.id))


def running_job(db, silent_for=timedelta(0), step=JobStepProcessingEnum.GENERATING_PROXY):
    job = queued_job(db)
    apply_job_event(db, JobUpdateEventSchema(
        job_id=job.id, status=JobStatusEnum.PROCESSING, step=step, step_progress=50, emitted_at=utc_now() - silent_for
    ))
    return job


def stored(db, job):
    db.expire_all()
    return db.get(Job, job.id)


def test_silent_job_is_failed_with_the_timeout_code(db):
    job = running_job(db, silent_for=TWO_HOURS)

    assert len(sweep_stalled_jobs(db)) == 1

    swept = stored(db, job)
    assert (swept.status, swept.error_code) == (JobStatusEnum.FAILED, JobErrorCodeEnum.TIMEOUT)
    assert "stopped reporting" in swept.error_message
    assert db.get(Project, job.project_id).status == ProjectStatus.INGESTION_FAILED
    assert db.get(MediaAsset, job.media_asset_id).status == MediaAssetStatus.FAILED
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.INGESTION_FAILED))
    assert entry.details["error_code"] == "timeout"


def test_job_that_keeps_reporting_is_left_alone(db):
    job = running_job(db, silent_for=timedelta(minutes=1))

    assert len(sweep_stalled_jobs(db)) == 0

    assert stored(db, job).status == JobStatusEnum.PROCESSING


def test_download_gets_a_longer_limit(db):
    job = running_job(db, silent_for=TWO_HOURS, step=JobStepProcessingEnum.DOWNLOADING_MEDIA)

    assert len(sweep_stalled_jobs(db)) == 0

    assert stored(db, job).status == JobStatusEnum.PROCESSING


def test_download_stalled_past_its_limit_is_failed(db):
    job = running_job(db, silent_for=timedelta(hours=6), step=JobStepProcessingEnum.DOWNLOADING_MEDIA)

    assert len(sweep_stalled_jobs(db)) == 1

    assert stored(db, job).error_code == JobErrorCodeEnum.TIMEOUT


def test_queued_job_is_not_swept(db):
    """A queued job is only waiting for a free worker."""
    job = queued_job(db)
    job.updated_at = utc_now() - timedelta(days=2)
    db.commit()

    assert len(sweep_stalled_jobs(db)) == 0

    assert stored(db, job).status == JobStatusEnum.QUEUED


def test_swept_job_no_longer_blocks_its_project(db):
    job = running_job(db, silent_for=TWO_HOURS)

    sweep_stalled_jobs(db)

    assert create_ingestion_job(db, str(job.project_id), IngestionParams(source_url=SAMPLE_URL), SAMPLE_URL) is not None


def test_late_event_of_a_swept_job_is_ignored(db):
    job = running_job(db, silent_for=TWO_HOURS)
    sweep_stalled_jobs(db)

    result = apply_job_event(db, JobUpdateEventSchema(job_id=job.id, status=JobStatusEnum.PROCESSING, step_progress=90))

    assert result.outcome == ApplyOutcome.IGNORED
    assert stored(db, job).status == JobStatusEnum.FAILED


def open_upload(db, storage, expired):
    session = start_upload(db, make_project(db), "Debate.mp4", 10, "video/mp4")
    chunk = storage.path(str(session.project_id), "uploads", str(session.id), "chunks", "000000")
    chunk.write_bytes(b"x" * 10)
    if expired:
        session.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    return session, chunk


def test_expired_upload_is_removed_with_its_chunks(db, storage):
    session, chunk = open_upload(db, storage, expired=True)
    session_id, asset_id = session.id, session.media_asset_id

    assert purge_expired_uploads(db, storage) == 1

    db.expire_all()
    assert not chunk.parent.parent.exists()
    assert db.get(UploadSession, session_id) is None
    assert db.get(MediaAsset, asset_id) is None


def test_upload_in_progress_is_kept(db, storage):
    session, chunk = open_upload(db, storage, expired=False)

    assert purge_expired_uploads(db, storage) == 0

    assert chunk.exists()
    assert db.get(UploadSession, session.id) is not None


def test_sweep_logs_what_it_did(session_factory, db, storage, caplog):
    running_job(db, silent_for=TWO_HOURS)
    open_upload(db, storage, expired=True)

    with caplog.at_level(logging.INFO, logger="app"):
        sweep_once(session_factory, storage)

    assert "1 stalled job(s), 1 abandoned upload(s)" in caplog.text


def test_clients_watching_are_told_when_a_job_is_swept(session_factory, db, storage, monkeypatch):
    monkeypatch.setenv("SWEEP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    job = running_job(db, silent_for=TWO_HOURS)
    hub = JobProgressHub()

    async def run():
        with hub.watch(job.project_id) as updates:
            task = asyncio.create_task(run_periodic_sweep(session_factory, storage, hub))
            update = await asyncio.wait_for(updates.get(), 20)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return update

    try:
        update = asyncio.run(run())
    finally:
        get_settings.cache_clear()

    assert (update.job_id, update.status, update.error_code) == (job.id, JobStatusEnum.FAILED, JobErrorCodeEnum.TIMEOUT)


def test_periodic_sweep_survives_a_failed_round(monkeypatch, caplog):
    monkeypatch.setenv("SWEEP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    rounds = []

    def flaky_sweep(session_factory, storage):
        rounds.append(1)
        if len(rounds) == 1:
            raise ConnectionError("database restarting")
        return []

    monkeypatch.setattr(sweeper, "sweep_once", flaky_sweep)

    async def run():
        task = asyncio.create_task(run_periodic_sweep(None, None, JobProgressHub()))
        while len(rounds) < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()

    assert "sweep failed" in caplog.text
