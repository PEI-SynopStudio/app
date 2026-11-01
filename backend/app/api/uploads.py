from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    CONTENT_TYPE_MAX_LENGTH,
    FILE_NAME_MAX_LENGTH,
    FILE_NAME_MIN_LENGTH,
    INGESTION_ROUTE_TAG,
    PROJECTS_ROUTE_PREFIX,
    UPLOAD_CHUNK_ROUTE,
    UPLOAD_COMPLETE_ROUTE,
    UPLOAD_ROUTE,
    UPLOADS_ROUTE,
    SourceType,
)
from app.services.storage.local import LocalStorage, get_storage
from app.services.video.uploads import (
    UploadSession,
    assemble_upload,
    discard_upload,
    get_upload,
    missing_chunks,
    save_chunk,
    start_upload,
)
from app.services.workflow.dispatcher import JobDispatcher, get_dispatcher
from app.services.workflow.ingestion_pipeline import IngestionJob
from app.services.workflow.status import IngestionStatus

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[INGESTION_ROUTE_TAG])


class UploadStart(BaseModel):
    file_name: str = Field(min_length=FILE_NAME_MIN_LENGTH, max_length=FILE_NAME_MAX_LENGTH)
    size_bytes: int
    content_type: Optional[str] = Field(default=None, max_length=CONTENT_TYPE_MAX_LENGTH)


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
        upload_id=session.upload_id,
        file_name=session.file_name,
        size_bytes=session.size_bytes,
        chunk_size=session.chunk_size,
        total_chunks=session.total_chunks,
        missing_chunks=missing_chunks(storage, session),
    )


# Open a chunked upload after checking the licence and the declared extension, MIME type and size.
# Source: MS2 FR02 – Step 1 (direct upload, chunked multipart upload for multi-GB files).
@router.post(UPLOADS_ROUTE, status_code=status.HTTP_201_CREATED, response_model=UploadProgress)
def create_upload(project_id: str, body: UploadStart, storage: LocalStorage = Depends(get_storage)):
    try:
        session = start_upload(storage, project_id, body.file_name, body.size_bytes, body.content_type)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    return _progress(storage, session)


@router.get(UPLOAD_ROUTE, response_model=UploadProgress)
def read_upload(project_id: str, upload_id: str, storage: LocalStorage = Depends(get_storage)):
    try:
        return _progress(storage, get_upload(storage, project_id, upload_id))
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
    storage: LocalStorage = Depends(get_storage),
):
    try:
        save_chunk(storage, get_upload(storage, project_id, upload_id), index, chunk.file)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Assemble the chunks into the project's source directory and queue the ingestion job.
# Source: MS2 FR02 – Step 2 (assembled in staging) and Outputs (asynchronous ingestion).
@router.post(UPLOAD_COMPLETE_ROUTE, status_code=status.HTTP_202_ACCEPTED, response_model=IngestionStatus)
def complete_upload(
    project_id: str,
    upload_id: str,
    storage: LocalStorage = Depends(get_storage),
    dispatcher: JobDispatcher = Depends(get_dispatcher),
):
    """If the job is refused (e.g. 409), the assembled file and session are kept, so this call can be retried."""
    try:
        session = assemble_upload(storage, get_upload(storage, project_id, upload_id))
        queued = dispatcher.dispatch(IngestionJob(
            project_id=project_id,
            source_type=SourceType.UPLOAD,
            source=session.file_name,
            staged_file=session.staged_file,
        ))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    discard_upload(storage, session)
    return queued
