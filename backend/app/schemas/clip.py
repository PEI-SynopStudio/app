from datetime import datetime
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, model_validator

from app.core.config import (
    CLIP_DURATION_DECIMALS,
    CLIP_MAX_SCENES,
    CLIP_MIN_SCENES,
    CLIP_NULLABLE_FIELDS,
    CLIP_SCENE_MIN_START,
    CLIP_TITLE_MAX_LENGTH,
    CLIP_TITLE_MIN_LENGTH,
    ERROR_SCENE_ORDER,
    Language,
)
from app.schemas.patch import reject_nulls

ClipTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=CLIP_TITLE_MIN_LENGTH, max_length=CLIP_TITLE_MAX_LENGTH)
]


class ClipScene(BaseModel):
    """A part of the original video, in seconds (FR11: the link to the source position)."""

    start: float = Field(ge=CLIP_SCENE_MIN_START, allow_inf_nan=False)
    end: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> "ClipScene":
        if self.end <= self.start:
            raise ValueError(ERROR_SCENE_ORDER.format(start=self.start, end=self.end))
        return self


# In the order they play in the clip; they may come from anywhere in the video (US21: reorder segments).
ClipScenes = Annotated[List[ClipScene], Field(min_length=CLIP_MIN_SCENES, max_length=CLIP_MAX_SCENES)]


class ClipCreate(BaseModel):
    title: ClipTitle
    scenes: ClipScenes
    # None = subtitles in the language spoken in the video.
    subtitle_language: Optional[Language] = None


class ClipUpdate(BaseModel):
    """PATCH body: omitted fields keep their value; subtitle_language null goes back to the spoken language."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[ClipTitle] = None
    scenes: Optional[ClipScenes] = None
    subtitle_language: Optional[Language] = None

    @model_validator(mode="after")
    def _only_nullable_fields_accept_null(self) -> "ClipUpdate":
        reject_nulls(self, CLIP_NULLABLE_FIELDS)
        return self


class ClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    scenes: List[ClipScene]
    subtitle_language: Optional[Language]
    position: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def duration_seconds(self) -> float:
        """Length of the clip: its scenes played one after the other."""
        return round(sum(scene.end - scene.start for scene in self.scenes), CLIP_DURATION_DECIMALS)