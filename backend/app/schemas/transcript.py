from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    ERROR_TRANSCRIPT_TIME_ORDER,
    LANGUAGE_CODE_PATTERN,
    SEGMENT_MIN_WORDS,
    TRANSCRIPT_COUNT_MIN,
    VIDEO_START_SECONDS,
)

Seconds = Annotated[float, Field(ge=VIDEO_START_SECONDS)]
Confidence = Annotated[float, Field(ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)]
Count = Annotated[int, Field(ge=TRANSCRIPT_COUNT_MIN)]


class _TimedText(BaseModel):
    text: str
    start: Seconds
    end: Seconds
    confidence: Confidence

    @model_validator(mode="after")
    def _validate(self) -> _TimedText:
        if self.end < self.start:
            raise ValueError(ERROR_TRANSCRIPT_TIME_ORDER.format(start=self.start, end=self.end))
        return self


class TranscriptWord(_TimedText):
    aligned: bool


class TranscriptSegment(_TimedText):
    avg_logprob: float
    no_speech_prob: Confidence
    compression_ratio: float
    temperature: float
    words: list[TranscriptWord] = Field(min_length=SEGMENT_MIN_WORDS)


class TranscriptDocument(BaseModel):
    ai_generated: Literal[True] = True
    language: str = Field(pattern=LANGUAGE_CODE_PATTERN)
    segments: list[TranscriptSegment]


class TranscriptionOutput(BaseModel):
    transcript_key: str
    language: str = Field(pattern=LANGUAGE_CODE_PATTERN)
    model_name: str
    model_revision: str
    alignment_model_name: str
    alignment_model_revision: str
    parameters: dict[str, Any]
    time_offset_seconds: Seconds
    segment_count: Count
    word_count: Count
    aligned_word_count: Count


class TranscriptMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    media_asset_id: uuid.UUID
    job_id: Optional[uuid.UUID]
    ai_generated: bool
    language: str
    model_name: str
    model_revision: str
    alignment_model_name: str
    alignment_model_revision: str
    parameters: dict[str, Any]
    time_offset_seconds: float
    segment_count: int
    word_count: int
    aligned_word_count: int
    created_at: datetime


class TranscriptResponse(TranscriptMetadata):

    segments: list[TranscriptSegment]
