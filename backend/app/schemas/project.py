from datetime import date, datetime
from typing import Annotated, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import (
    PROJECT_AUTHOR_MAX_LENGTH,
    PROJECT_FIELD_MIN_LENGTH,
    PROJECT_MIN_SPEAKERS,
    PROJECT_TITLE_MAX_LENGTH,
    PROJECT_TITLE_MIN_LENGTH,
    LicenseType,
    ProjectStatus,
)

SpeakerName = Annotated[str, Field(min_length=PROJECT_FIELD_MIN_LENGTH, max_length=PROJECT_AUTHOR_MAX_LENGTH)]


class ProjectCreate(BaseModel):
    """Mandatory metadata of a new project (FR01)."""

    title: str = Field(min_length=PROJECT_TITLE_MIN_LENGTH, max_length=PROJECT_TITLE_MAX_LENGTH)
    author: str = Field(min_length=PROJECT_FIELD_MIN_LENGTH, max_length=PROJECT_AUTHOR_MAX_LENGTH)
    speakers: List[SpeakerName] = Field(min_length=PROJECT_MIN_SPEAKERS)
    recording_date: date
    license_type: LicenseType
    copyright_notice: str = Field(min_length=PROJECT_FIELD_MIN_LENGTH)
    licence_confirmed: bool
    authorship_confirmed: bool


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    author: str
    speakers: List[str]
    recording_date: date
    license_type: LicenseType
    copyright_notice: str
    licence_confirmed: bool
    authorship_confirmed: bool
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
