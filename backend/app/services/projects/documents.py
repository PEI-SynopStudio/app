import os
import uuid
from pathlib import Path
from typing import BinaryIO, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_DETAIL_DOCUMENT_ID,
    AUDIT_DETAIL_FILE_NAME,
    AUDIT_DETAIL_SIZE_BYTES,
    CONTENT_TYPE_MAX_LENGTH,
    DOCUMENT_KEY_FORMAT,
    ERROR_DOCUMENT_LIMIT,
    ERROR_DOCUMENT_NAME,
    ERROR_DOCUMENT_NOT_FOUND,
    ERROR_INVALID_DOCUMENT_ID,
    ERROR_UNSUPPORTED_EXTENSION,
    ERROR_UPLOAD_EMPTY,
    ERROR_UPLOAD_TOO_LARGE,
    EXTENSION_SEPARATOR,
    FILE_NAME_MAX_LENGTH,
    FILE_NAME_MIN_LENGTH,
    LIST_SEPARATOR,
    AuditAction,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import Project, ProjectDocument, User
from app.services.audit.audit import record_audit
from app.services.projects.projects import get_project
from app.services.storage.object_storage import ObjectStorage


class DocumentNotFoundError(LookupError):
    pass


def list_documents(db: Session, project_id: str) -> List[ProjectDocument]:
    return list(get_project(db, project_id).documents)


# Store a supporting document (slides, paper, glossary) in the project's object storage.
# Source: MS2 FR03 (PDF, PPTX, DOCX or TXT), US08; MS3 (documents encrypted at rest by SeaweedFS); FR18.
def add_document(
    db: Session,
    object_storage: ObjectStorage,
    project_id: str,
    file_name: Optional[str],
    content_type: Optional[str],
    data: BinaryIO,
    actor: Optional[User] = None,
) -> ProjectDocument:
    """The text extraction and indexing of FR03 run later, in a worker; here the file is only checked and kept."""
    project = get_project(db, project_id)
    settings = get_settings()
    extension = _check_file_name(file_name, settings.allowed_document_extensions)
    size = _size(data)
    if size == 0:
        raise ValueError(ERROR_UPLOAD_EMPTY)
    if size > settings.max_document_bytes:
        raise ValueError(ERROR_UPLOAD_TOO_LARGE.format(size=size, limit=settings.max_document_bytes))
    count = db.scalar(select(func.count()).select_from(ProjectDocument).where(ProjectDocument.project_id == project.id))
    if count >= settings.max_documents_per_project:
        raise ValueError(ERROR_DOCUMENT_LIMIT.format(limit=settings.max_documents_per_project))

    document_id = uuid.uuid4()
    document = ProjectDocument(
        id=document_id,
        project_id=project.id,
        file_name=file_name,
        file_type=extension,
        content_type=content_type if content_type and len(content_type) <= CONTENT_TYPE_MAX_LENGTH else None,
        size_bytes=size,
        storage_key=DOCUMENT_KEY_FORMAT.format(document_id=document_id, extension=extension),
    )
    # The object goes first: if the storage fails, no row refers to a missing file.
    object_storage.put_stream(str(project.id), document.storage_key, data)
    db.add(document)
    record_audit(
        db,
        project.id,
        AuditAction.DOCUMENT_ADDED,
        {AUDIT_DETAIL_DOCUMENT_ID: str(document_id), AUDIT_DETAIL_FILE_NAME: file_name, AUDIT_DETAIL_SIZE_BYTES: size},
        actor=actor,
    )
    _touch(project)
    db.commit()
    return document


# Remove a supporting document and its file.
# Source: MS2 FR03; MS3 §1.4.3 (no data kept after the user removes it); FR18.
def delete_document(
    db: Session, object_storage: ObjectStorage, project_id: str, document_id: str, actor: Optional[User] = None
) -> None:
    """The object goes first: if the storage fails, the row stays and the deletion can be repeated."""
    project = get_project(db, project_id)
    document = db.get(ProjectDocument, _parse_document_id(document_id))
    if document is None or document.project_id != project.id:
        raise DocumentNotFoundError(ERROR_DOCUMENT_NOT_FOUND.format(document_id=document_id))
    object_storage.delete(str(project.id), document.storage_key)
    record_audit(
        db,
        project.id,
        AuditAction.DOCUMENT_REMOVED,
        {AUDIT_DETAIL_DOCUMENT_ID: str(document.id), AUDIT_DETAIL_FILE_NAME: document.file_name},
        actor=actor,
    )
    db.delete(document)
    _touch(project)
    db.commit()


def _check_file_name(file_name: Optional[str], allowed: tuple) -> str:
    """Return the lower-case extension, or raise ValueError; the name itself is never used as a storage key."""
    if not file_name or len(file_name) > FILE_NAME_MAX_LENGTH:
        raise ValueError(ERROR_DOCUMENT_NAME.format(minimum=FILE_NAME_MIN_LENGTH, maximum=FILE_NAME_MAX_LENGTH))
    extension = Path(file_name).suffix.lower().lstrip(EXTENSION_SEPARATOR)
    if extension not in allowed:
        raise ValueError(ERROR_UNSUPPORTED_EXTENSION.format(extension=extension, allowed=LIST_SEPARATOR.join(allowed)))
    return extension


def _size(data: BinaryIO) -> int:
    """Size of the received file; the stream is put back at its start for the upload."""
    data.seek(0, os.SEEK_END)
    size = data.tell()
    data.seek(0)
    return size


def _touch(project: Project) -> None:
    project.updated_at = utc_now()


def _parse_document_id(document_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(document_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_DOCUMENT_ID.format(document_id=document_id))