from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.core.config import (
    ERROR_EVENT_CODE_NOT_ALLOWED,
    ERROR_EVENT_CODE_REQUIRED,
    ERROR_JOB_SOURCE_REQUIRED,
    ERROR_JOB_TIME_ORDER,
    FIRST_JOB_ATTEMPT,
    LANGUAGE_CODE_PATTERN,
    PROGRESS_MAX,
    PROGRESS_MIN,
    get_settings,
)
from app.schemas.enums import (
    AcousticProfileEnum,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    JobTypeEnum,
)
from app.schemas.timecode import parse_time


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _StrictModel(BaseModel):
    # Unknown fields (e.g. a "video_path" sent by a client) are a 422 instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")


class IngestionParams(_StrictModel):
    job_type: Literal["ingestion"] = "ingestion"
    source_url: HttpUrl | None = None
    media_id: UUID | None = None  # reference to an upload
    time_start: str | None = None
    time_end: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> IngestionParams:
        if (self.source_url is None) == (self.media_id is None):
            raise ValueError(ERROR_JOB_SOURCE_REQUIRED)
        start = parse_time(self.time_start) if self.time_start is not None else None
        end = parse_time(self.time_end) if self.time_end is not None else None

        if start is not None and end is not None and end <= start:
            raise ValueError(ERROR_JOB_TIME_ORDER)
        return self


class TranscriptionParams(_StrictModel):
    """The speech model is worker configuration; clients cannot choose it."""

    job_type: Literal["transcription"] = "transcription"
    media_id: UUID
    language: str = Field(default_factory=lambda: get_settings().default_language, pattern=LANGUAGE_CODE_PATTERN)
    acoustic_profile: AcousticProfileEnum | None = None


JobParameters = Annotated[IngestionParams | TranscriptionParams, Field(discriminator="job_type")]


class JobCreateSchema(_StrictModel):
    """Body of POST /projects/{project_id}/jobs.

    The project ID comes from the URL path and the type from parameters.job_type,
    so there are no two sources of truth that can disagree.
    """

    parameters: JobParameters

    @property
    def job_type(self) -> JobTypeEnum:
        return JobTypeEnum(self.parameters.job_type)


class JobRequestMessage(BaseModel):
    """API to worker: published to the jobs exchange with routing key = job_type."""

    job_id: UUID
    project_id: UUID
    attempt: int = Field(default=FIRST_JOB_ATTEMPT, ge=FIRST_JOB_ATTEMPT)
    parameters: JobParameters
    # Uploads only, set by the API and never by a client: the chunks to assemble and the target file name.
    upload_id: UUID | None = None
    staged_file: str | None = None
    requested_at: datetime = Field(default_factory=_utcnow)


class JobUpdateEventSchema(BaseModel):
    """Worker to API: progress, completion or failure."""

    job_id: UUID
    event_id: UUID = Field(default_factory=uuid4)
    attempt: int = Field(default=FIRST_JOB_ATTEMPT, ge=FIRST_JOB_ATTEMPT)
    step: JobStepProcessingEnum | None = None
    step_progress: float = Field(ge=PROGRESS_MIN, le=PROGRESS_MAX)
    status: JobStatusEnum
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    emitted_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _validate(self) -> JobUpdateEventSchema:
        if self.status == JobStatusEnum.FAILED and self.error_code is None:
            raise ValueError(ERROR_EVENT_CODE_REQUIRED)
        if self.status != JobStatusEnum.FAILED and self.error_code is not None:
            raise ValueError(ERROR_EVENT_CODE_NOT_ALLOWED)
        return self


class JobStatusResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    project_id: UUID
    job_type: JobTypeEnum
    status: JobStatusEnum
    step: JobStepProcessingEnum | None = None
    step_progress: float = Field(default=PROGRESS_MIN, ge=PROGRESS_MIN, le=PROGRESS_MAX)
    progress: float = Field(default=PROGRESS_MIN, ge=PROGRESS_MIN, le=PROGRESS_MAX)
    attempt: int = Field(default=FIRST_JOB_ATTEMPT, ge=FIRST_JOB_ATTEMPT)
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
