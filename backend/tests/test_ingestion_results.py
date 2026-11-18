import uuid
from datetime import date

from sqlalchemy import func, select

from app.core.config import (
    AuditAction,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    JobTypeEnum,
    LicenseType,
    MediaAssetStatus,
    ProjectStatus,
    SourceType,
)
from app.database.models import AudioTrack, AuditLog, Job, MediaAsset, Project
from app.schemas.job import IngestionParams, JobUpdateEventSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.workflow.jobs import apply_job_event, create_ingestion_job, fail_job, queue_job

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
OUTPUT = {
    "source_type": "url",
    "source": SAMPLE_URL,
    "container": "mov,mp4",
    "duration_seconds": 600.0,
    "size_bytes": 1000,
    "width": 1280,
    "height": 720,
    "aspect_ratio": "16:9",
    "frame_rate": 25.0,
    "is_vfr": True,
    "video_codec": "h264",
    "audio_codec": "aac",
    "sample_rate": 48000,
    "channels": 2,
    "created_at": "2026-11-08T12:00:00Z",
    "source_key": "source/original.mp4",
    "proxy_key": "proxy/proxy.mp4",
    "audio_key": "audio/audio.wav",
    "waveform_key": "analysis/waveform.json",
    "keyframes_key": "analysis/keyframes.json",
}


def make_ingestion(db):
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
    asset = MediaAsset(
        project_id=project.id, source_type=SourceType.URL, source_url=SAMPLE_URL, status=MediaAssetStatus.PROCESSING
    )
    db.add(asset)
    db.commit()
    job = create_ingestion_job(
        db, str(project.id), IngestionParams(source_url=SAMPLE_URL), SAMPLE_URL, media_asset_id=asset.id
    )
    return queue_job(db, job), project, asset


def start(db, job):
    apply_job_event(db, JobUpdateEventSchema(
        job_id=job.id, status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INSPECTING_MEDIA, step_progress=0
    ))


def complete(db, job):
    return apply_job_event(db, JobUpdateEventSchema(
        job_id=job.id, status=JobStatusEnum.COMPLETED, step_progress=100, output=OUTPUT
    ))


def audit_details(db, project, action):
    query = select(AuditLog).where(AuditLog.project_id == project.id, AuditLog.action == action)
    return db.scalar(query).details


def test_a_cut_upload_records_where_it_really_starts(db):
    job, _, asset = make_ingestion(db)
    asset.time_start_seconds = 12.0
    db.commit()
    start(db, job)

    apply_job_event(db, JobUpdateEventSchema(
        job_id=job.id, status=JobStatusEnum.COMPLETED, step_progress=100, output={**OUTPUT, "time_start_seconds": 8.3}
    ))

    db.expire_all()
    assert db.get(MediaAsset, asset.id).time_start_seconds == 8.3


def test_a_completed_job_keeps_the_requested_start_when_nothing_was_cut(db):
    job, _, asset = make_ingestion(db)
    asset.time_start_seconds = 12.0
    db.commit()
    start(db, job)

    complete(db, job)

    db.expire_all()
    assert db.get(MediaAsset, asset.id).time_start_seconds == 12.0


def test_a_running_job_marks_the_project_as_ingesting(db):
    job, project, _ = make_ingestion(db)

    start(db, job)

    db.expire_all()
    assert db.get(Project, project.id).status == ProjectStatus.INGESTING


def test_a_completed_job_saves_the_technical_metadata(db):
    job, project, asset = make_ingestion(db)
    start(db, job)

    complete(db, job)

    db.expire_all()
    stored = db.get(MediaAsset, asset.id)
    assert stored.status == MediaAssetStatus.READY
    assert (stored.width, stored.height, stored.aspect_ratio) == (1280, 720, "16:9")
    assert (stored.duration_seconds, stored.frame_rate, stored.sample_rate) == (600.0, 25.0, 48000)
    assert stored.is_vfr is True
    assert stored.keyframes_key == "analysis/keyframes.json"
    assert (stored.source_key, stored.proxy_key) == ("source/original.mp4", "proxy/proxy.mp4")
    track = db.scalar(select(AudioTrack).where(AudioTrack.media_asset_id == asset.id))
    assert (track.sample_rate, track.channels, track.format, track.storage_key) == (
        16000, 1, "wav", "audio/audio.wav"
    )
    assert track.waveform_key == "analysis/waveform.json"
    assert db.get(Project, project.id).status == ProjectStatus.INGESTED
    assert audit_details(db, project, AuditAction.INGESTION_COMPLETED) == {"job_id": str(job.id)}


def test_a_repeated_completion_does_not_duplicate_the_audio_track(db):
    job, _, _ = make_ingestion(db)
    start(db, job)
    complete(db, job)

    complete(db, job)

    assert db.scalar(select(func.count()).select_from(AudioTrack)) == 1


def test_a_failed_job_marks_the_project_as_ingestion_failed(db):
    job, project, asset = make_ingestion(db)
    start(db, job)

    apply_job_event(db, JobUpdateEventSchema(
        job_id=job.id,
        status=JobStatusEnum.FAILED,
        step_progress=0,
        error_code=JobErrorCodeEnum.SILENT_AUDIO,
        error_message="Silent",
    ))

    db.expire_all()
    assert db.get(MediaAsset, asset.id).status == MediaAssetStatus.FAILED
    assert db.get(Project, project.id).status == ProjectStatus.INGESTION_FAILED
    assert audit_details(db, project, AuditAction.INGESTION_FAILED) == {
        "job_id": str(job.id), "error_code": "silent_audio"
    }


def test_a_job_failed_by_the_api_also_marks_the_project(db):
    job, project, _ = make_ingestion(db)

    fail_job(db, job, JobErrorCodeEnum.INTERNAL_ERROR, "Broker unavailable")

    db.expire_all()
    assert db.get(Project, project.id).status == ProjectStatus.INGESTION_FAILED


def test_other_job_types_do_not_change_the_project(db):
    _, project, _ = make_ingestion(db)
    transcription = Job(
        id=uuid.uuid4(),
        project_id=project.id,
        job_type=JobTypeEnum.TRANSCRIPTION,
        status=JobStatusEnum.QUEUED,
        parameters={},
    )
    db.add(transcription)
    db.commit()

    apply_job_event(db, JobUpdateEventSchema(
        job_id=transcription.id,
        status=JobStatusEnum.PROCESSING,
        step=JobStepProcessingEnum.TRANSCRIBING,
        step_progress=0,
    ))

    db.expire_all()
    assert db.get(Project, project.id).status == ProjectStatus.DRAFT
