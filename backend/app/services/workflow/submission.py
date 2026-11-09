import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    DOWNLOAD_FILE,
    ERROR_JOB_DISPATCH_FAILED,
    ERROR_STORAGE_UNAVAILABLE,
    LOG_JOB_DISPATCH_FAILED,
    REPLACEABLE_ASSET_STATUSES,
    JobErrorCodeEnum,
    MediaAssetStatus,
    SourceType,
)
from app.database.models import Job, MediaAsset, UploadSession
from app.schemas.job import IngestionParams, JobRequestMessage
from app.schemas.timecode import parse_time
from app.services.projects.projects import require_ingestion_allowed
from app.services.storage.local import LocalStorage
from app.services.storage.object_storage import ObjectStorage, ObjectStorageError
from app.services.video.uploads import close_upload, source_key
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.jobs import create_ingestion_job, fail_job, queue_job

logger = logging.getLogger(__name__)


# Register an authorised link as a media asset and queue its ingestion.
# Source: MS2 FR02 – Step 1 (link input) and Outputs (asynchronous processing); FR01 – Acceptance Criteria.
def submit_url_ingestion(
    db: Session,
    storage: LocalStorage,
    object_storage: ObjectStorage,
    dispatcher: JobDispatcher,
    project_id: str,
    url: str,
    time_start: Optional[str],
    time_end: Optional[str],
) -> Job:
    project = require_ingestion_allowed(db, project_id)
    asset = MediaAsset(
        project_id=project.id,
        source_type=SourceType.URL,
        source_url=url,
        status=MediaAssetStatus.PROCESSING,
        source_key=source_key(DOWNLOAD_FILE),
        time_start_seconds=_seconds(time_start),
        time_end_seconds=_seconds(time_end),
    )
    db.add(asset)
    db.flush()  # assigns the ID; refusing the job rolls the asset back
    params = IngestionParams(source_url=url, time_start=time_start, time_end=time_end)
    job = create_ingestion_job(db, project_id, params, url, media_asset_id=asset.id)
    _replace_previous_assets(db, storage, object_storage, job)
    return _queue_and_dispatch(
        db, dispatcher, job, JobRequestMessage(job_id=job.id, project_id=project.id, parameters=params)
    )


# Queue the ingestion of a fully received upload and close its session.
# Source: MS2 FR02 – Step 2 and Outputs (asynchronous ingestion, no UI blocking).
def submit_upload_ingestion(
    db: Session,
    storage: LocalStorage,
    object_storage: ObjectStorage,
    dispatcher: JobDispatcher,
    session: UploadSession,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
) -> Job:
    """If the job is refused (e.g. 409) or the broker or storage fails, the session stays and the upload can be retried."""
    params = IngestionParams(media_id=session.media_asset_id, time_start=time_start, time_end=time_end)
    job = create_ingestion_job(
        db, str(session.project_id), params, session.file_name, media_asset_id=session.media_asset_id
    )
    asset = db.get(MediaAsset, session.media_asset_id)
    asset.source_key = source_key(session.staged_file)
    asset.time_start_seconds, asset.time_end_seconds = _seconds(time_start), _seconds(time_end)
    asset.status = MediaAssetStatus.PROCESSING
    _replace_previous_assets(db, storage, object_storage, job)
    request = JobRequestMessage(
        job_id=job.id,
        project_id=session.project_id,
        parameters=params,
        storage_upload_id=session.storage_upload_id,
        staged_file=session.staged_file,
        file_name=session.file_name,
    )
    _queue_and_dispatch(db, dispatcher, job, request)
    close_upload(db, session)
    return job


def _replace_previous_assets(db: Session, storage: LocalStorage, object_storage: ObjectStorage, job: Job) -> None:
    """A new ingestion replaces the finished video of the project, in the database and in storage.

    Runs before the job is dispatched, so the worker never finds or overwrites the old files.
    Uploads still in progress are kept: they belong to a video that has not been submitted yet.
    The objects go first: if the storage fails, the job fails and the old records stay, so no object is left without one.
    """
    query = select(MediaAsset).where(
        MediaAsset.project_id == job.project_id,
        MediaAsset.id != job.media_asset_id,
        MediaAsset.status.in_(REPLACEABLE_ASSET_STATUSES),
    )
    assets = db.scalars(query).all()
    keys = [key for asset in assets for key in _asset_keys(asset)]
    project_id = str(job.project_id)
    try:
        for key in keys:
            object_storage.delete(project_id, key)
    except ObjectStorageError:
        fail_job(db, job, JobErrorCodeEnum.INTERNAL_ERROR, ERROR_STORAGE_UNAVAILABLE)
        raise
    for asset in assets:
        db.delete(asset)
    db.commit()
    for key in keys:
        storage.delete(project_id, key)


def _asset_keys(asset: MediaAsset) -> List[str]:
    candidates = [asset.source_key, asset.proxy_key, asset.keyframes_key]
    if asset.audio_track is not None:
        candidates += [asset.audio_track.storage_key, asset.audio_track.waveform_key]
    return [key for key in candidates if key is not None]


def _queue_and_dispatch(db: Session, dispatcher: JobDispatcher, job: Job, request: JobRequestMessage) -> Job:
    """Queued is committed first, so a worker event never finds the job still pending."""
    queue_job(db, job)
    try:
        dispatcher.dispatch(request)
    except Exception:
        logger.exception(LOG_JOB_DISPATCH_FAILED, job.id)
        fail_job(db, job, JobErrorCodeEnum.INTERNAL_ERROR, ERROR_JOB_DISPATCH_FAILED)
        raise
    return job


def _seconds(timecode: Optional[str]) -> Optional[float]:
    return float(parse_time(timecode)) if timecode is not None else None
