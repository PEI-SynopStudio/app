import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import (
    ERROR_JOB_DISPATCH_FAILED,
    LOG_JOB_DISPATCH_FAILED,
    JobErrorCodeEnum,
    MediaAssetStatus,
    SourceType,
)
from app.database.models import Job, MediaAsset, UploadSession
from app.schemas.job import IngestionParams, JobRequestMessage
from app.schemas.timecode import parse_time
from app.services.projects.projects import require_ingestion_allowed
from app.services.video.uploads import close_upload
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.jobs import create_ingestion_job, fail_job, queue_job

logger = logging.getLogger(__name__)


# Register an authorised link as a media asset and queue its ingestion.
# Source: MS2 FR02 – Step 1 (link input) and Outputs (asynchronous processing); FR01 – Acceptance Criteria.
def submit_url_ingestion(
    db: Session,
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
        time_start_seconds=_seconds(time_start),
        time_end_seconds=_seconds(time_end),
    )
    db.add(asset)
    db.flush()  # assigns the ID; refusing the job rolls the asset back
    params = IngestionParams(source_url=url, time_start=time_start, time_end=time_end)
    job = create_ingestion_job(db, project_id, params, url, media_asset_id=asset.id)
    return _queue_and_dispatch(
        db, dispatcher, job, JobRequestMessage(job_id=job.id, project_id=project.id, parameters=params)
    )


# Queue the ingestion of a fully received upload and close its session.
# Source: MS2 FR02 – Step 2 and Outputs (asynchronous ingestion, no UI blocking).
def submit_upload_ingestion(db: Session, dispatcher: JobDispatcher, session: UploadSession) -> Job:
    """If the job is refused (e.g. 409), nothing changes, so the upload can be completed again later."""
    params = IngestionParams(media_id=session.media_asset_id)
    job = create_ingestion_job(
        db, str(session.project_id), params, session.file_name, media_asset_id=session.media_asset_id
    )
    request = JobRequestMessage(
        job_id=job.id,
        project_id=session.project_id,
        parameters=params,
        upload_id=session.id,
        staged_file=session.staged_file,
        file_name=session.file_name,
    )
    close_upload(db, session)
    return _queue_and_dispatch(db, dispatcher, job, request)


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
