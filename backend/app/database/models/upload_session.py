import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import (
    CONTENT_TYPE_MAX_LENGTH,
    DB_ON_DELETE_CASCADE,
    FILE_NAME_MAX_LENGTH,
    FK_MEDIA_ASSET_ID,
    FK_PROJECT_ID,
    TABLE_UPLOAD_SESSIONS,
)
from app.database.base import Base, utc_now


class UploadSession(Base):
    """A chunked upload in progress (FR02 step 1); the chunks themselves stay in storage."""

    __tablename__ = TABLE_UPLOAD_SESSIONS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(FK_MEDIA_ASSET_ID, ondelete=DB_ON_DELETE_CASCADE), unique=True
    )
    # Original name from the client: kept for the metadata, never used as a path.
    file_name: Mapped[str] = mapped_column(String(FILE_NAME_MAX_LENGTH))
    content_type: Mapped[Optional[str]] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    chunk_size: Mapped[int]
    total_chunks: Mapped[int]
    # Server-chosen name of the assembled file in the project's source directory.
    staged_file: Mapped[str] = mapped_column(String(FILE_NAME_MAX_LENGTH))
    assembled: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
