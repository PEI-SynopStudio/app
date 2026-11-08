import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    ERROR_INGESTION_NOT_STARTED,
    INGESTION_ROUTE_TAG,
    INGESTION_STATUS_ROUTE,
    PROJECTS_ROUTE_PREFIX,
    TIMECODE_MAX_LENGTH,
    URL_INGESTION_ROUTE,
    URL_MAX_LENGTH,
    JobStatusEnum,
)
from app.database.session import get_db
from app.schemas.job import JobStatusResponseSchema
from app.services.projects.projects import get_project
from app.services.storage.local import LocalStorage, get_storage
from app.services.video.metadata import TechnicalMetadata
from app.services.video.sources import validate_source_url, validate_time_range
from app.services.workflow.dispatcher import JobDispatcher, get_dispatcher
from app.services.workflow.jobs import latest_ingestion_job
from app.services.workflow.submission import submit_url_ingestion

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[INGESTION_ROUTE_TAG])


class UrlIngestionRequest(BaseModel):
    url: str = Field(max_length=URL_MAX_LENGTH)
    start_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)
    end_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)


class IngestionOverview(BaseModel):
    job: JobStatusResponseSchema
    metadata: Optional[TechnicalMetadata] = None


# Accept an authorised link and queue its ingestion; the slow checks (yt-dlp probe) run in the job.
# Source: MS2 FR02 – Step 1 (link input, URL syntax and domain) and Outputs (asynchronous, no UI blocking).
@router.post(URL_INGESTION_ROUTE, status_code=status.HTTP_202_ACCEPTED, response_model=JobStatusResponseSchema)
def ingest_url(
    project_id: str,
    body: UrlIngestionRequest,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    dispatcher: JobDispatcher = Depends(get_dispatcher),
):
    try:
        url = validate_source_url(body.url)
        # Format and order only; the video duration is known after the probe, inside the job.
        validate_time_range(body.start_time, body.end_time, math.inf)
        return submit_url_ingestion(db, storage, dispatcher, project_id, url, body.start_time, body.end_time)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Return the latest ingestion job (progress or failure details) and, once completed, the technical metadata.
# Source: MS2 FR02 – Outputs (progress) and Step 3 ('Ingestion Failed' with details).
@router.get(INGESTION_STATUS_ROUTE, response_model=IngestionOverview)
def read_ingestion(project_id: str, db: Session = Depends(get_db)):
    try:
        project = get_project(db, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc

    job = latest_ingestion_job(db, project.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_INGESTION_NOT_STARTED.format(project_id=project_id),
        )
    metadata = TechnicalMetadata.model_validate(job.output) if job.status == JobStatusEnum.COMPLETED else None
    return IngestionOverview(job=JobStatusResponseSchema.model_validate(job), metadata=metadata)
