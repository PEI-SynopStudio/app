from datetime import date, datetime
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.config import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_CAPTION_STYLE,
    DEFAULT_PROJECT_LANGUAGE,
    PROJECT_AUTHOR_MAX_LENGTH,
    PROJECT_DESCRIPTION_MAX_LENGTH,
    PROJECT_FIELD_MIN_LENGTH,
    PROJECT_MIN_SPEAKERS,
    PROJECT_NULLABLE_FIELDS,
    PROJECT_TITLE_MAX_LENGTH,
    PROJECT_TITLE_MIN_LENGTH,
    AspectRatio,
    CaptionStyle,
    Language,
    LicenseType,
    ProjectStatus,
)
from app.schemas.clip import ClipResponse
from app.schemas.document import DocumentResponse
from app.schemas.patch import reject_nulls

SpeakerName = Annotated[str, Field(min_length=PROJECT_FIELD_MIN_LENGTH, max_length=PROJECT_AUTHOR_MAX_LENGTH)]
ProjectTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=PROJECT_TITLE_MIN_LENGTH, max_length=PROJECT_TITLE_MAX_LENGTH),
]
# The prompt given to the AI; a blank text is stored as no prompt.
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=PROJECT_DESCRIPTION_MAX_LENGTH),
    AfterValidator(lambda text: text or None),
]


class ProjectCreate(BaseModel):
    """Mandatory metadata of a new project and the settings of its clips"""

    title: ProjectTitle
    author: str = Field(min_length=PROJECT_FIELD_MIN_LENGTH, max_length=PROJECT_AUTHOR_MAX_LENGTH)
    speakers: List[SpeakerName] = Field(min_length=PROJECT_MIN_SPEAKERS)
    recording_date: date
    license_type: LicenseType
    copyright_notice: str = Field(min_length=PROJECT_FIELD_MIN_LENGTH)
    licence_confirmed: bool
    authorship_confirmed: bool

    description: Optional[Description] = None
    aspect_ratio: AspectRatio = DEFAULT_ASPECT_RATIO
    language: Language = DEFAULT_PROJECT_LANGUAGE
    # null = no subtitles.
    caption_style: Optional[CaptionStyle] = DEFAULT_CAPTION_STYLE


class ProjectUpdate(BaseModel):
    """PATCH body: omitted fields keep their value; description and caption_style accept null.

    The licence and authorship fields are not editable here: they are confirmed once, with an audit record.
    """

    model_config = ConfigDict(extra="forbid")

    title: Optional[ProjectTitle] = None
    description: Optional[Description] = None
    aspect_ratio: Optional[AspectRatio] = None
    language: Optional[Language] = None
    caption_style: Optional[CaptionStyle] = None

    @model_validator(mode="after")
    def _only_nullable_fields_accept_null(self) -> "ProjectUpdate":
        reject_nulls(self, PROJECT_NULLABLE_FIELDS)
        return self


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
    description: Optional[str]
    aspect_ratio: AspectRatio
    language: Language
    caption_style: Optional[CaptionStyle]
    created_at: datetime
    updated_at: datetime
    clips: List[ClipResponse]
    documents: List[DocumentResponse]


class ProjectSummary(BaseModel):
    """One card of the project library."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: Optional[str]
    status: ProjectStatus
    aspect_ratio: AspectRatio
    language: Language
    caption_style: Optional[CaptionStyle]
    clip_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: List[ProjectSummary]
    # Number of projects that match the filters, for the pagination.
    total: int
    limit: int
    offset: int