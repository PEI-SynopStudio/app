import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    ASPECT_RATIO_MAX_LENGTH,
    CODEC_NAME_MAX_LENGTH,
    CONTAINER_NAME_MAX_LENGTH,
    DB_DELETE_ORPHAN_CASCADE,
    DB_ON_DELETE_CASCADE,
    FILE_NAME_MAX_LENGTH,
    FK_PROJECT_ID,
    STORAGE_KEY_MAX_LENGTH,
    TABLE_MEDIA_ASSETS,
    URL_MAX_LENGTH,
    MediaAssetStatus,
    SourceType,
)
from app.database.base import Base, enum_type, utc_now


class MediaAsset(Base):
    """A source video and its technical metadata (FR02 step 6)."""

    __tablename__ = TABLE_MEDIA_ASSETS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    source_type: Mapped[SourceType] = mapped_column(enum_type(SourceType))
    source_url: Mapped[Optional[str]] = mapped_column(String(URL_MAX_LENGTH))
    file_name: Mapped[Optional[str]] = mapped_column(String(FILE_NAME_MAX_LENGTH))
    status: Mapped[MediaAssetStatus] = mapped_column(enum_type(MediaAssetStatus))
    time_start_seconds: Mapped[Optional[float]]
    time_end_seconds: Mapped[Optional[float]]

    # Filled when ingestion completes.
    container: Mapped[Optional[str]] = mapped_column(String(CONTAINER_NAME_MAX_LENGTH))
    video_codec: Mapped[Optional[str]] = mapped_column(String(CODEC_NAME_MAX_LENGTH))
    audio_codec: Mapped[Optional[str]] = mapped_column(String(CODEC_NAME_MAX_LENGTH))
    duration_seconds: Mapped[Optional[float]]
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    width: Mapped[Optional[int]]
    height: Mapped[Optional[int]]
    aspect_ratio: Mapped[Optional[str]] = mapped_column(String(ASPECT_RATIO_MAX_LENGTH))
    frame_rate: Mapped[Optional[float]]
    is_vfr: Mapped[Optional[bool]]
    sample_rate: Mapped[Optional[int]]
    channels: Mapped[Optional[int]]
    source_key: Mapped[Optional[str]] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    proxy_key: Mapped[Optional[str]] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    keyframes_key: Mapped[Optional[str]] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    project: Mapped["Project"] = relationship(back_populates="media_assets")
    audio_track: Mapped[Optional["AudioTrack"]] = relationship(
        back_populates="media_asset", cascade=DB_DELETE_ORPHAN_CASCADE, passive_deletes=True
    )
