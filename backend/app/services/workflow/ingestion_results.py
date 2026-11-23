from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import (
    ASSET_METADATA_FIELDS,
    AUDIO_CHANNELS,
    AUDIO_CONTAINER,
    AUDIO_SAMPLE_RATE,
    AUDIT_DETAIL_ERROR_CODE,
    AUDIT_DETAIL_JOB_ID,
    AuditAction,
    JobStatusEnum,
    JobTypeEnum,
    MediaAssetStatus,
    ProjectStatus,
)
from app.database.models import AudioTrack, Job, MediaAsset, Project
from app.services.audit.audit import record_audit
from app.services.video.metadata import IngestionOutput


# Reflect the state of an ingestion job on its project and media asset; the caller commits.
# Source: MS2 FR02 – Step 3 ('Ingestion Failed' with details) and Step 6 (metadata saved to the database); FR18.
def record_ingestion_outcome(db: Session, job: Job) -> None:
    """Called right after a job changes; other job types and statuses change nothing here."""
    if job.job_type != JobTypeEnum.INGESTION:
        return
    project = db.get(Project, job.project_id)
    asset = db.get(MediaAsset, job.media_asset_id) if job.media_asset_id is not None else None

    if job.status == JobStatusEnum.PROCESSING:
        project.status = ProjectStatus.INGESTING
    elif job.status == JobStatusEnum.COMPLETED:
        _record_success(db, job, project, asset)
    elif job.status == JobStatusEnum.FAILED:
        _record_failure(db, job, project, asset)
    elif job.status == JobStatusEnum.CANCELLED:
        _record_cancellation(db, job, project, asset)


def _record_success(db: Session, job: Job, project: Project, asset: Optional[MediaAsset]) -> None:
    if asset is not None:
        output = IngestionOutput.model_validate(job.output)
        for field in ASSET_METADATA_FIELDS:
            setattr(asset, field, getattr(output, field))
        # A cut without re-encoding starts on the keyframe before the requested time (FR11).
        if output.time_start_seconds is not None:
            asset.time_start_seconds = output.time_start_seconds
        asset.status = MediaAssetStatus.READY
        db.add(AudioTrack(
            media_asset_id=asset.id,
            sample_rate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            format=AUDIO_CONTAINER,
            storage_key=output.audio_key,
            waveform_key=output.waveform_key,
        ))
    project.status = ProjectStatus.INGESTED
    record_audit(db, project.id, AuditAction.INGESTION_COMPLETED, {AUDIT_DETAIL_JOB_ID: str(job.id)})


def _record_failure(db: Session, job: Job, project: Project, asset: Optional[MediaAsset]) -> None:
    if asset is not None:
        asset.status = MediaAssetStatus.FAILED
    project.status = ProjectStatus.INGESTION_FAILED
    record_audit(
        db,
        project.id,
        AuditAction.INGESTION_FAILED,
        {AUDIT_DETAIL_JOB_ID: str(job.id), AUDIT_DETAIL_ERROR_CODE: job.error_code.value},
    )

def _record_cancellation(db: Session, job: Job, project: Project, asset: Optional[MediaAsset]) -> None:
    if asset is not None:
        asset.status = MediaAssetStatus.FAILED
    project.status = ProjectStatus.INGESTION_FAILED
    record_audit(
        db,
        project.id,
        AuditAction.INGESTION_CANCELLED,
        {AUDIT_DETAIL_JOB_ID: str(job.id)},
    )