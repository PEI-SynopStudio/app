import math
import os
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    ALLOWED_UPLOAD_MIME_TYPES,
    AUDIT_DETAIL_FILE_NAME,
    AUDIT_DETAIL_SIZE_BYTES,
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
    LIST_SEPARATOR,
    SOURCE_DIR,
    TMP_SUFFIX,
    UPLOAD_CHUNKS_DIR,
    UPLOADS_DIR,
    AuditAction,
    MediaAssetStatus,
    SourceType,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import MediaAsset, UploadSession
from app.services.audit.audit import record_audit
from app.services.projects.projects import require_ingestion_allowed
from app.services.storage.local import LocalStorage


class UploadNotFoundError(LookupError):
    pass


class UploadIncompleteError(Exception):
    pass


# Validate the declared file (extension, MIME type, size) and open an upload session with a fixed chunk size.
# Source: MS2 FR02 – Step 1 (direct upload, extension and MIME check, chunked multipart upload for multi-GB files).
def start_upload(
    db: Session, project_id: str, file_name: str, size_bytes: int, content_type: Optional[str]
) -> UploadSession:
    """Refuse at once when the licence is not confirmed (FR01) or the file is not acceptable."""
    project = require_ingestion_allowed(db, project_id)
    extension = _check_declared_file(file_name, size_bytes, content_type)

    settings = get_settings()
    upload_id = uuid.uuid4()
    asset = MediaAsset(
        project_id=project.id,
        source_type=SourceType.UPLOAD,
        file_name=file_name,
        status=MediaAssetStatus.UPLOADING,
    )
    db.add(asset)
    db.flush()  # assigns the ID the session refers to
    session = UploadSession(
        id=upload_id,
        project_id=project.id,
        media_asset_id=asset.id,
        file_name=file_name,
        content_type=content_type or None,
        size_bytes=size_bytes,
        chunk_size=settings.upload_chunk_size_bytes,
        total_chunks=math.ceil(size_bytes / settings.upload_chunk_size_bytes),
        staged_file=str(upload_id) + EXTENSION_SEPARATOR + extension,
        expires_at=utc_now() + timedelta(seconds=settings.upload_session_ttl_seconds),
    )
    db.add(session)
    record_audit(
        db,
        project.id,
        AuditAction.UPLOAD_STARTED,
        {AUDIT_DETAIL_FILE_NAME: file_name, AUDIT_DETAIL_SIZE_BYTES: size_bytes},
    )
    db.commit()
    return session


def get_upload(db: Session, project_id: str, upload_id: str) -> UploadSession:
    session = db.get(UploadSession, _parse_upload_id(upload_id))
    if session is None or str(session.project_id) != project_id:
        raise UploadNotFoundError(ERROR_UPLOAD_NOT_FOUND.format(upload_id=upload_id))
    return session


def missing_chunks(storage: LocalStorage, session: UploadSession) -> List[int]:
    return [index for index in range(session.total_chunks) if not _chunk_path(storage, session, index).is_file()]


def require_all_chunks(storage: LocalStorage, session: UploadSession) -> None:
    missing = missing_chunks(storage, session)
    if missing:
        raise UploadIncompleteError(ERROR_UPLOAD_INCOMPLETE.format(count=len(missing), first=missing[0]))


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


def close_upload(db: Session, session: UploadSession) -> None:
    """Called once the job is queued: the chunks now belong to the job and the asset is being processed."""
    db.get(MediaAsset, session.media_asset_id).status = MediaAssetStatus.PROCESSING
    db.delete(session)
    db.commit()


# Concatenate all chunks, in order, into the project's source directory, then remove the upload directory.
# Source: MS2 FR02 – Step 2 (upload assembled in staging storage).
def assemble_chunks(storage: LocalStorage, project_id: str, upload_id: str, staged_file: str) -> Path:
    """Blocking (files can have several GB): run it in a job, never in an endpoint.

    Each chunk is deleted once copied, so the disk holds about one copy of the file, not two.
    """
    upload_dir = storage.project_dir(project_id) / UPLOADS_DIR / upload_id
    target = storage.path(project_id, SOURCE_DIR, staged_file)
    # Chunk names are zero-padded, so sorting them by name is sorting them by index.
    chunks = sorted(path for path in (upload_dir / UPLOAD_CHUNKS_DIR).iterdir() if path.suffix != TMP_SUFFIX)
    with open(target, FILE_WRITE_MODE) as out:
        for chunk in chunks:
            with open(chunk, FILE_READ_MODE) as src:
                shutil.copyfileobj(src, out, COPY_BUFFER_BYTES)
            chunk.unlink()
    shutil.rmtree(upload_dir, ignore_errors=True)
    return target


# Remove the chunks and the records of the uploads that were started but never completed.
# Source: MS2 FR02 – Step 1 (chunked upload); the session expiry set when the upload starts.
def purge_expired_uploads(db: Session, storage: LocalStorage) -> int:
    """Returns how many uploads were removed; deleting the media asset also removes its session (database cascade)."""
    sessions = db.scalars(select(UploadSession).where(UploadSession.expires_at < utc_now())).all()
    for session in sessions:
        storage.delete_upload(str(session.project_id), str(session.id))
        db.delete(db.get(MediaAsset, session.media_asset_id))
        db.commit()
    return len(sessions)


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


def _parse_upload_id(upload_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(upload_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_UPLOAD_ID.format(upload_id=upload_id))


def _chunk_path(storage: LocalStorage, session: UploadSession, index: int) -> Path:
    return storage.path(
        str(session.project_id), UPLOADS_DIR, str(session.id), UPLOAD_CHUNKS_DIR, CHUNK_FILE_FORMAT.format(index=index)
    )
