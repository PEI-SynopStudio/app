import math
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, List, Optional

from pydantic import BaseModel

from app.core.config import (
    ALLOWED_UPLOAD_MIME_TYPES,
    CHUNK_FILE_FORMAT,
    COPY_BUFFER_BYTES,
    ERROR_CHUNK_INDEX_OUT_OF_RANGE,
    ERROR_CHUNK_SIZE_MISMATCH,
    ERROR_INVALID_UPLOAD_ID,
    ERROR_UNSUPPORTED_EXTENSION,
    ERROR_UNSUPPORTED_MIME_TYPE,
    ERROR_UPLOAD_EMPTY,
    ERROR_UPLOAD_INCOMPLETE,
    ERROR_UPLOAD_NOT_FOUND,
    ERROR_UPLOAD_TOO_LARGE,
    EXTENSION_SEPARATOR,
    FILE_READ_MODE,
    FILE_WRITE_MODE,
    JSON_DUMP_MODE,
    LIST_SEPARATOR,
    SOURCE_DIR,
    TMP_SUFFIX,
    UPLOAD_CHUNKS_DIR,
    UPLOAD_SESSION_FILE,
    UPLOADS_DIR,
    get_settings,
)
from app.services.projects.projects import require_ingestion_allowed
from app.services.storage.local import LocalStorage


class UploadSession(BaseModel):
    upload_id: str
    project_id: str
    # Original name from the client: kept for the metadata, never used as a path.
    file_name: str
    content_type: Optional[str] = None
    size_bytes: int
    chunk_size: int
    total_chunks: int
    # Server-chosen name of the assembled file in the project's source directory.
    staged_file: str
    assembled: bool = False
    created_at: datetime


class UploadNotFoundError(LookupError):
    pass


class UploadIncompleteError(Exception):
    pass


# Validate the declared file (extension, MIME type, size) and open an upload session with a fixed chunk size.
# Source: MS2 FR02 – Step 1 (direct upload, extension and MIME check, chunked multipart upload for multi-GB files).
def start_upload(
    storage: LocalStorage, project_id: str, file_name: str, size_bytes: int, content_type: Optional[str]
) -> UploadSession:
    """Refuse at once when the licence is not confirmed (FR01) or the file is not acceptable."""
    require_ingestion_allowed(storage, project_id)
    extension = _check_declared_file(file_name, size_bytes, content_type)

    upload_id = str(uuid.uuid4())
    chunk_size = get_settings().upload_chunk_size_bytes
    session = UploadSession(
        upload_id=upload_id,
        project_id=project_id,
        file_name=file_name,
        content_type=content_type or None,
        size_bytes=size_bytes,
        chunk_size=chunk_size,
        total_chunks=math.ceil(size_bytes / chunk_size),
        staged_file=upload_id + EXTENSION_SEPARATOR + extension,
        created_at=datetime.now(timezone.utc),
    )
    _save(storage, session)
    return session


def get_upload(storage: LocalStorage, project_id: str, upload_id: str) -> UploadSession:
    data = storage.read_json(project_id, _session_name(_normalize_upload_id(upload_id)))
    if data is None:
        raise UploadNotFoundError(ERROR_UPLOAD_NOT_FOUND.format(upload_id=upload_id))
    return UploadSession.model_validate(data)


def missing_chunks(storage: LocalStorage, session: UploadSession) -> List[int]:
    return [index for index in range(session.total_chunks) if not _chunk_path(storage, session, index).is_file()]


# Store one chunk; every chunk has the session's chunk size except the last, which holds the remainder.
# Source: MS2 FR02 – Step 1 (chunked multipart upload).
def save_chunk(storage: LocalStorage, session: UploadSession, index: int, data: BinaryIO) -> None:
    """Write through a temp file and rename, so a retried or interrupted chunk never leaves a partial file."""
    last = session.total_chunks - 1
    if not 0 <= index <= last:
        raise ValueError(ERROR_CHUNK_INDEX_OUT_OF_RANGE.format(index=index, last=last))
    expected = session.chunk_size if index < last else session.size_bytes - session.chunk_size * last

    target = _chunk_path(storage, session, index)
    tmp = target.with_name(target.name + TMP_SUFFIX)
    written = 0
    try:
        with open(tmp, FILE_WRITE_MODE) as out:
            # Stop reading once the chunk is too big instead of storing an oversized body.
            while written <= expected and (block := data.read(COPY_BUFFER_BYTES)):
                out.write(block)
                written += len(block)
        if written != expected:
            raise ValueError(ERROR_CHUNK_SIZE_MISMATCH.format(index=index, expected=expected, actual=written))
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


# Concatenate all chunks, in order, into the project's source directory.
# Source: MS2 FR02 – Step 2 (upload assembled in staging storage).
def assemble_upload(storage: LocalStorage, session: UploadSession) -> UploadSession:
    """Idempotent: an already assembled session is returned unchanged, so 'complete' can be retried.

    Each chunk is deleted once copied, so the disk holds about one copy of the file, not two.
    """
    if session.assembled:
        return session
    missing = missing_chunks(storage, session)
    if missing:
        raise UploadIncompleteError(ERROR_UPLOAD_INCOMPLETE.format(count=len(missing), first=missing[0]))

    target = storage.path(session.project_id, SOURCE_DIR, session.staged_file)
    with open(target, FILE_WRITE_MODE) as out:
        for index in range(session.total_chunks):
            chunk = _chunk_path(storage, session, index)
            with open(chunk, FILE_READ_MODE) as src:
                shutil.copyfileobj(src, out, COPY_BUFFER_BYTES)
            chunk.unlink()

    assembled = session.model_copy(update={"assembled": True})
    _save(storage, assembled)
    return assembled


def discard_upload(storage: LocalStorage, session: UploadSession) -> None:
    """Remove the session and any remaining chunks (the assembled source file is kept)."""
    shutil.rmtree(storage.project_dir(session.project_id) / UPLOADS_DIR / session.upload_id, ignore_errors=True)


def _check_declared_file(file_name: str, size_bytes: int, content_type: Optional[str]) -> str:
    """Return the lower-case extension, or raise ValueError; the content itself is inspected during ingestion."""
    settings = get_settings()
    extension = Path(file_name).suffix.lower().lstrip(EXTENSION_SEPARATOR)
    if extension not in settings.allowed_extensions:
        raise ValueError(ERROR_UNSUPPORTED_EXTENSION.format(
            extension=extension, allowed=LIST_SEPARATOR.join(settings.allowed_extensions)
        ))
    if content_type and content_type.lower() not in ALLOWED_UPLOAD_MIME_TYPES:
        raise ValueError(ERROR_UNSUPPORTED_MIME_TYPE.format(content_type=content_type))
    if size_bytes <= 0:
        raise ValueError(ERROR_UPLOAD_EMPTY)
    if size_bytes > settings.max_upload_bytes:
        raise ValueError(ERROR_UPLOAD_TOO_LARGE.format(size=size_bytes, limit=settings.max_upload_bytes))
    return extension


def _normalize_upload_id(upload_id: str) -> str:
    # Upload IDs are UUIDs, which also keeps them from being used for path traversal.
    try:
        return str(uuid.UUID(upload_id))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_UPLOAD_ID.format(upload_id=upload_id))


def _session_name(upload_id: str) -> str:
    return PurePosixPath(UPLOADS_DIR, upload_id, UPLOAD_SESSION_FILE).as_posix()


def _chunk_path(storage: LocalStorage, session: UploadSession, index: int) -> Path:
    return storage.path(
        session.project_id, UPLOADS_DIR, session.upload_id, UPLOAD_CHUNKS_DIR, CHUNK_FILE_FORMAT.format(index=index)
    )


def _save(storage: LocalStorage, session: UploadSession) -> None:
    storage.write_json(session.project_id, _session_name(session.upload_id), session.model_dump(mode=JSON_DUMP_MODE))
