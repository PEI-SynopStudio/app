import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import ForeignKey, Index, Text, Uuid, and_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import (
    DB_ON_DELETE_CASCADE,
    DB_ON_DELETE_SET_NULL,
    FIRST_JOB_ATTEMPT,
    FK_MEDIA_ASSET_ID,
    FK_PROJECT_ID,
    JOB_ACTIVE_INGESTION_INDEX,
    JOB_ACTIVE_STATUSES,
    PROGRESS_MIN,
    TABLE_JOBS,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    JobTypeEnum,
)
from app.database.base import Base, enum_type, utc_now


class Job(Base):
    """Persisted state of an asynchronous job; JobSnapshot holds the same state for the state machine."""

    __tablename__ = TABLE_JOBS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    media_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(FK_MEDIA_ASSET_ID, ondelete=DB_ON_DELETE_SET_NULL), index=True
    )
    job_type: Mapped[JobTypeEnum] = mapped_column(enum_type(JobTypeEnum))
    status: Mapped[JobStatusEnum] = mapped_column(enum_type(JobStatusEnum), default=JobStatusEnum.PENDING)
    step: Mapped[Optional[JobStepProcessingEnum]] = mapped_column(enum_type(JobStepProcessingEnum))
    step_progress: Mapped[float] = mapped_column(default=PROGRESS_MIN)
    progress: Mapped[float] = mapped_column(default=PROGRESS_MIN)
    attempt: Mapped[int] = mapped_column(default=FIRST_JOB_ATTEMPT)
    error_code: Mapped[Optional[JobErrorCodeEnum]] = mapped_column(enum_type(JobErrorCodeEnum))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    started_at: Mapped[Optional[datetime]]
    finished_at: Mapped[Optional[datetime]]
    last_event_at: Mapped[Optional[datetime]]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    @property
    def job_id(self) -> uuid.UUID:
        """The name JobStatusResponseSchema reads."""
        return self.id


# One active ingestion per project, guaranteed by the database even with concurrent requests.
Index(
    JOB_ACTIVE_INGESTION_INDEX,
    Job.project_id,
    unique=True,
    postgresql_where=and_(Job.job_type == JobTypeEnum.INGESTION, Job.status.in_(JOB_ACTIVE_STATUSES)),
)
