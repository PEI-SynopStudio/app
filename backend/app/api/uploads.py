import math
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    CONTENT_TYPE_MAX_LENGTH,
    FILE_NAME_MAX_LENGTH,
    FILE_NAME_MIN_LENGTH,
    INGESTION_ROUTE_TAG,
    PROJECTS_ROUTE_PREFIX,
    TIMECODE_MAX_LENGTH,
    UPLOAD_CHUNK_ROUTE,
    UPLOAD_COMPLETE_ROUTE,
    UPLOAD_ROUTE,
    UPLOADS_ROUTE,
)
from app.database.models import UploadSession
from app.database.session import get_db
from app.schemas.job import JobStatusResponseSchema
from app.services.storage.local import LocalStorage, get_storage
from app.services.video.sources import validate_time_range
from app.services.video.uploads import (
    get_upload,
    missing_chunks,
    require_all_chunks,
    save_chunk,
    start_upload,
)
from app.services.workflow.dispatcher import JobDispatcher, get_dispatcher
from app.services.workflow.submission import submit_upload_ingestion

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[INGESTION_ROUTE_TAG])


class UploadStart(BaseModel):
    file_name: str = Field(min_length=FILE_NAME_MIN_LENGTH, max_length=FILE_NAME_MAX_LENGTH)
    size_bytes: int
    content_type: Optional[str] = Field(default=None, max_length=CONTENT_TYPE_MAX_LENGTH)


class UploadCompletion(BaseModel):
    start_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)
    end_time: Optional[str] = Field(default=None, max_length=TIMECODE_MAX_LENGTH)


class UploadProgress(BaseModel):
    upload_id: str
    file_name: str
    size_bytes: int
    chunk_size: int
    total_chunks: int
    # Lets the client resume an interrupted upload by sending only these chunks.
    missing_chunks: List[int]


def _progress(storage: LocalStorage, session: UploadSession) -> UploadProgress:
    return UploadProgress(
        upload_id=str(session.id),
        file_name=session.file_name,
        size_bytes=session.size_bytes,
        chunk_size=session.chunk_size,
        total_chunks=session.total_chunks,
        missing_chunks=missing_chunks(storage, session),
    )


# Open a chunked upload after checking the licence and the declared extension, MIME type and size.
# Source: MS2 FR02 – Step 1 (direct upload, chunked multipart upload for multi-GB files).
@router.post(UPLOADS_ROUTE, status_code=status.HTTP_201_CREATED, response_model=UploadProgress)
def create_upload(
    project_id: str,
    body: UploadStart,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
):
    try:
        session = start_upload(db, project_id, body.file_name, body.size_bytes, body.content_type)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    return _progress(storage, session)


@router.get(UPLOAD_ROUTE, response_model=UploadProgress)
def read_upload(
    project_id: str,
    upload_id: str,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
):
    try:
        return _progress(storage, get_upload(db, project_id, upload_id))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Receive one chunk as multipart form data (field "chunk"); sending the same chunk again replaces it.
# Source: MS2 FR02 – Step 1 (chunked multipart upload).
@router.put(UPLOAD_CHUNK_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def upload_chunk(
    project_id: str,
    upload_id: str,
    index: int,
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
):
    try:
        session = get_upload(db, project_id, upload_id)
        # Free the database connection: storing a chunk can take a while.
        db.close()
        save_chunk(storage, session, index, chunk.file)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Check that every chunk arrived and queue the job, which assembles them and applies the optional time range.
# Source: MS2 FR02 – Inputs (optional start/end timecodes), Step 2 and Outputs (asynchronous ingestion, no UI blocking).
@router.post(UPLOAD_COMPLETE_ROUTE, status_code=status.HTTP_202_ACCEPTED, response_model=JobStatusResponseSchema)
def complete_upload(
    project_id: str,
    upload_id: str,
    body: Optional[UploadCompletion] = None,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    dispatcher: JobDispatcher = Depends(get_dispatcher),
):
    """If the job is refused (e.g. 409), the chunks and the session are kept, so this call can be retried."""
    time_range = body or UploadCompletion()
    try:
        # Format and order only; the video duration is known after the inspection, inside the job.
        validate_time_range(time_range.start_time, time_range.end_time, math.inf)
        session = get_upload(db, project_id, upload_id)
        require_all_chunks(storage, session)
        return submit_upload_ingestion(db, storage, dispatcher, session, time_range.start_time, time_range.end_time)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
