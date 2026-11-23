import uuid
from datetime import datetime
from typing import Optional


from sqlalchemy import BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    CONTENT_TYPE_MAX_LENGTH,
    DB_ON_DELETE_CASCADE,
    FILE_NAME_MAX_LENGTH,
    FILE_TYPE_MAX_LENGTH,
    FK_PROJECT_ID,
    STORAGE_KEY_MAX_LENGTH,
    TABLE_PROJECT_DOCUMENTS,
)
from app.database.base import Base, utc_now


class ProjectDocument(Base):
    """A supporting document (slides, paper, glossary) that gives the AI context about the video (FR03)."""

    __tablename__ = TABLE_PROJECT_DOCUMENTS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    # Original name from the client: shown in the interface, never used as a storage key.
    file_name: Mapped[str] = mapped_column(String(FILE_NAME_MAX_LENGTH))
    # Lower-case extension, e.g. "pdf".
    file_type: Mapped[str] = mapped_column(String(FILE_TYPE_MAX_LENGTH))
    content_type: Mapped[Optional[str]] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Server-chosen key in the project's object storage.
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="documents")