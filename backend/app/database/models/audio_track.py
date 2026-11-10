import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    CODEC_NAME_MAX_LENGTH,
    DB_ON_DELETE_CASCADE,
    FK_MEDIA_ASSET_ID,
    STORAGE_KEY_MAX_LENGTH,
    TABLE_AUDIO_TRACKS,
)
from app.database.base import Base, utc_now


class AudioTrack(Base):
    """The normalized audio of a source video and its waveform (FR02 step 4)."""

    __tablename__ = TABLE_AUDIO_TRACKS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(FK_MEDIA_ASSET_ID, ondelete=DB_ON_DELETE_CASCADE), unique=True
    )
    sample_rate: Mapped[int]
    channels: Mapped[int]
    format: Mapped[str] = mapped_column(String(CODEC_NAME_MAX_LENGTH))
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    waveform_key: Mapped[Optional[str]] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    media_asset: Mapped["MediaAsset"] = relationship(back_populates="audio_track")
