import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    DB_DELETE_ORPHAN_CASCADE,
    DB_ON_DELETE_CASCADE,
    DB_ON_DELETE_SET_NULL,
    FK_JOB_ID,
    FK_MEDIA_ASSET_ID,
    FK_PROJECT_ID,
    FK_TRANSCRIPT_ID,
    FK_TRANSCRIPT_SEGMENT_ID,
    LANGUAGE_CODE_MAX_LENGTH,
    MODEL_NAME_MAX_LENGTH,
    MODEL_REVISION_MAX_LENGTH,
    STORAGE_KEY_MAX_LENGTH,
    TABLE_TRANSCRIPT_SEGMENTS,
    TABLE_TRANSCRIPT_WORDS,
    TABLE_TRANSCRIPTS,
    TRANSCRIPT_SEGMENTS_TIME_INDEX,
    TRANSCRIPT_WORDS_TIME_INDEX,
)
from app.database.base import Base, utc_now


class Transcript(Base):

    __tablename__ = TABLE_TRANSCRIPTS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(FK_MEDIA_ASSET_ID, ondelete=DB_ON_DELETE_CASCADE), unique=True
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey(FK_JOB_ID, ondelete=DB_ON_DELETE_SET_NULL))
    language: Mapped[str] = mapped_column(String(LANGUAGE_CODE_MAX_LENGTH))
    model_name: Mapped[str] = mapped_column(String(MODEL_NAME_MAX_LENGTH))
    model_revision: Mapped[str] = mapped_column(String(MODEL_REVISION_MAX_LENGTH))
    alignment_model_name: Mapped[str] = mapped_column(String(MODEL_NAME_MAX_LENGTH))
    alignment_model_revision: Mapped[str] = mapped_column(String(MODEL_REVISION_MAX_LENGTH))
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    time_offset_seconds: Mapped[float]
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    ai_generated: Mapped[bool] = mapped_column(default=True)
    segment_count: Mapped[int]
    word_count: Mapped[int]
    aligned_word_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    segments: Mapped[List["TranscriptSegment"]] = relationship(
        back_populates="transcript",
        cascade=DB_DELETE_ORPHAN_CASCADE,
        passive_deletes=True,
        order_by="TranscriptSegment.position",
    )


class TranscriptSegment(Base):

    __tablename__ = TABLE_TRANSCRIPT_SEGMENTS
    __table_args__ = (
        UniqueConstraint("transcript_id", "position"),
        Index(TRANSCRIPT_SEGMENTS_TIME_INDEX, "transcript_id", "start_seconds"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_TRANSCRIPT_ID, ondelete=DB_ON_DELETE_CASCADE))
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    start_seconds: Mapped[float]
    end_seconds: Mapped[float]
    confidence: Mapped[float]
    avg_logprob: Mapped[float]
    no_speech_prob: Mapped[float]
    compression_ratio: Mapped[float]
    temperature: Mapped[float]

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    words: Mapped[List["TranscriptWord"]] = relationship(
        back_populates="segment",
        cascade=DB_DELETE_ORPHAN_CASCADE,
        passive_deletes=True,
        order_by="TranscriptWord.position",
    )


class TranscriptWord(Base):

    __tablename__ = TABLE_TRANSCRIPT_WORDS
    __table_args__ = (
        UniqueConstraint("transcript_id", "position"),
        Index(TRANSCRIPT_WORDS_TIME_INDEX, "transcript_id", "start_seconds"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_TRANSCRIPT_ID, ondelete=DB_ON_DELETE_CASCADE))
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(FK_TRANSCRIPT_SEGMENT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True
    )
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    start_seconds: Mapped[float]
    end_seconds: Mapped[float]
    confidence: Mapped[float]
    aligned: Mapped[bool]

    segment: Mapped[TranscriptSegment] = relationship(back_populates="words")
