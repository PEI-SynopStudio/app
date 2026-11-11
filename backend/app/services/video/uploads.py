import math
import os
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import BinaryIO, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    ALLOWED_UPLOAD_MIME_TYPES,
    AUDIT_DETAIL_FILE_NAME,
    AUDIT_DETAIL_SIZE_BYTES,
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
    LIST_SEPARATOR,
    SOURCE_DIR,
    AuditAction,
    MediaAssetStatus,
    SourceType,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import MediaAsset, UploadSession
from app.services.audit.audit import record_audit
from app.services.projects.projects import require_ingestion_allowed
from app.services.storage.object_storage import ObjectStorage


class UploadNotFoundError(LookupError):
    pass


class UploadIncompleteError(Exception):
    pass


def source_key(file_name: str) -> str:
    """Storage key of a project's source video."""
    return PurePosixPath(SOURCE_DIR, file_name).as_posix()


# Validate the declared file (extension, MIME type, size) and open an upload session with a fixed chunk size.
# Source: MS2 FR02 – Step 1 (direct upload, extension and MIME check, chunked multipart upload for multi-GB files).
def start_upload(
    db: Session,
    object_storage: ObjectStorage,
    project_id: str,
    file_name: str,
    size_bytes: int,
    content_type: Optional[str],
) -> UploadSession:
    """Refuse at once when the licence is not confirmed (FR01) or the file is not acceptable."""
    project = require_ingestion_allowed(db, project_id)
    extension = _check_declared_file(file_name, size_bytes, content_type)

    settings = get_settings()
    upload_id = uuid.uuid4()
    staged_file = str(upload_id) + EXTENSION_SEPARATOR + extension
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
        staged_file=staged_file,
        storage_upload_id=object_storage.start_chunked_upload(str(project.id), source_key(staged_file)),
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


def missing_chunks(object_storage: ObjectStorage, session: UploadSession) -> List[int]:
    received = object_storage.received_chunks(
        str(session.project_id), source_key(session.staged_file), session.storage_upload_id
    )
    return [index for index in range(session.total_chunks) if index not in received]


def require_all_chunks(object_storage: ObjectStorage, session: UploadSession) -> None:
    missing = missing_chunks(object_storage, session)
    if missing:
        raise UploadIncompleteError(ERROR_UPLOAD_INCOMPLETE.format(count=len(missing), first=missing[0]))


# Store one chunk; every chunk has the session's chunk size except the last, which holds the remainder.
# Source: MS2 FR02 – Step 1 (chunked multipart upload).
def save_chunk(object_storage: ObjectStorage, session: UploadSession, index: int, data: BinaryIO) -> None:
    """Measured before it is sent, so a chunk of the wrong size never reaches the storage."""
    last = session.total_chunks - 1
    if not 0 <= index <= last:
        raise ValueError(ERROR_CHUNK_INDEX_OUT_OF_RANGE.format(index=index, last=last))
    expected = session.chunk_size if index < last else session.size_bytes - session.chunk_size * last

    received = data.seek(0, os.SEEK_END)
    data.seek(0)
    if received != expected:
        raise ValueError(ERROR_CHUNK_SIZE_MISMATCH.format(index=index, expected=expected, actual=received))
    object_storage.put_chunk(
        str(session.project_id), source_key(session.staged_file), session.storage_upload_id, index, data
    )


def close_upload(db: Session, session: UploadSession) -> None:
    """Called once the job is on the broker: the chunks now belong to the job."""
    db.delete(session)
    db.commit()


# Remove the chunks and the records of the uploads that were started but never completed.
# Source: MS2 FR02 – Step 1 (chunked upload); the session expiry set when the upload starts.
def purge_expired_uploads(db: Session, object_storage: ObjectStorage) -> int:
    """Returns how many uploads were removed; deleting the media asset also removes its session (database cascade)."""
    sessions = db.scalars(select(UploadSession).where(UploadSession.expires_at < utc_now())).all()
    for session in sessions:
        object_storage.abort_chunked_upload(
            str(session.project_id), source_key(session.staged_file), session.storage_upload_id
        )
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
