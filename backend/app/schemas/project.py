from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ARCHIVED = "archived"


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus | None = None


class Project(BaseModel):
    id: str
    owner_id: str
    title: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime
    updated_at: datetime


class ProjectLibrary(BaseModel):
    items: list[Project]
    total: int