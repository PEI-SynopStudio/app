import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import (
    ERROR_INGESTION_NOT_STARTED,
    INGESTION_ROUTE_TAG,
    INGESTION_STATUS_ROUTE,
    PROJECTS_ROUTE_PREFIX,
    TIMECODE_MAX_LENGTH,
    URL_INGESTION_ROUTE,
    URL_MAX_LENGTH,
    SourceType,
)
from app.services.projects.projects import LicenceNotConfirmedError, ProjectNotFoundError, get_project
from app.services.storage.local import LocalStorage, get_storage
from app.services.video.metadata import TechnicalMetadata, get_technical_metadata
from app.services.video.sources import validate_source_url, validate_time_range
from app.services.workflow.dispatcher import IngestionAlreadyRunningError, JobDispatcher, get_dispatcher
from app.services.workflow.ingestion_pipeline import IngestionJob
from app.services.workflow.status import IngestionStatus, get_status

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[INGESTION_ROUTE_TAG])


class UrlIngestionRequest(BaseModel):
    url: str = Field(max_length=URL_MAX_LENGTH)
    start_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)
    end_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)


class IngestionOverview(BaseModel):
    status: IngestionStatus
    metadata: Optional[TechnicalMetadata] = None


def _http_error(exc: Exception) -> HTTPException:
    """Map service exceptions to HTTP errors with the original, descriptive message."""
    if isinstance(exc, ProjectNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, LicenceNotConfirmedError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, IngestionAlreadyRunningError):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))


# Accept an authorised link and queue its ingestion; the slow checks (yt-dlp probe) run in the job.
# Source: MS2 FR02 – Step 1 (link input, URL syntax and domain) and Outputs (asynchronous, no UI blocking).
@router.post(URL_INGESTION_ROUTE, status_code=status.HTTP_202_ACCEPTED, response_model=IngestionStatus)
def ingest_url(
    project_id: str,
    body: UrlIngestionRequest,
    storage: LocalStorage = Depends(get_storage),
    dispatcher: JobDispatcher = Depends(get_dispatcher),
):
    try:
        url = validate_source_url(body.url)
        # Format and order only; the video duration is known after the probe, inside the job.
        validate_time_range(body.start_time, body.end_time, math.inf)
        job = IngestionJob(
            project_id=project_id,
            source_type=SourceType.URL,
            source=url,
            start_time=body.start_time,
            end_time=body.end_time,
        )
        return dispatcher.dispatch(job)
    except (ValueError, ProjectNotFoundError, LicenceNotConfirmedError, IngestionAlreadyRunningError) as exc:
        raise _http_error(exc) from exc


# Return the current ingestion stage (or the failure details) and, once saved, the technical metadata.
# Source: MS2 FR02 – Outputs (progress) and Step 3 ('Ingestion Failed' with details).
@router.get(INGESTION_STATUS_ROUTE, response_model=IngestionOverview)
def read_ingestion(project_id: str, storage: LocalStorage = Depends(get_storage)):
    try:
        get_project(storage, project_id)
    except (ValueError, ProjectNotFoundError) as exc:
        raise _http_error(exc) from exc

    current = get_status(storage, project_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_INGESTION_NOT_STARTED.format(project_id=project_id),
        )
    return IngestionOverview(status=current, metadata=get_technical_metadata(storage, project_id))
