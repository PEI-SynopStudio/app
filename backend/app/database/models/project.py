import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    DB_DELETE_ORPHAN_CASCADE,
    DB_ON_DELETE_RESTRICT,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_CAPTION_STYLE,
    DEFAULT_PROJECT_LANGUAGE,
    FK_USER_ID,
    PROJECT_AUTHOR_MAX_LENGTH,
    PROJECT_TITLE_MAX_LENGTH,
    TABLE_PROJECTS,
    AspectRatio,
    CaptionStyle,
    Language,
    LicenseType,
    ProjectStatus,
)
from app.database.base import Base, enum_type, utc_now


class Project(Base):
    """A recording with its authorship and licensing metadata and the settings of its clips"""

    __tablename__ = TABLE_PROJECTS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(FK_USER_ID, ondelete=DB_ON_DELETE_RESTRICT), index=True
    )
    title: Mapped[str] = mapped_column(String(PROJECT_TITLE_MAX_LENGTH))
    author: Mapped[str] = mapped_column(String(PROJECT_AUTHOR_MAX_LENGTH))
    speakers: Mapped[List[str]] = mapped_column(JSONB, default=list)
    recording_date: Mapped[date]
    license_type: Mapped[LicenseType] = mapped_column(enum_type(LicenseType))
    copyright_notice: Mapped[str] = mapped_column(Text)
    licence_confirmed: Mapped[bool]
    authorship_confirmed: Mapped[bool]
    status: Mapped[ProjectStatus] = mapped_column(enum_type(ProjectStatus), default=ProjectStatus.DRAFT)

    # Prompt for the AI: context that helps choose the best moments (FR09).
    description: Mapped[Optional[str]] = mapped_column(Text)
    aspect_ratio: Mapped[AspectRatio] = mapped_column(enum_type(AspectRatio), default=DEFAULT_ASPECT_RATIO)
    # Language spoken in the video; the subtitles use it unless a clip asks for a translation.
    language: Mapped[Language] = mapped_column(enum_type(Language), default=DEFAULT_PROJECT_LANGUAGE)
    # None = the clips have no subtitles. evaluates_none: an explicit None is saved as NULL;
    # without it, SQLAlchemy would treat None as "not given" and apply the default style.
    caption_style: Mapped[Optional[CaptionStyle]] = mapped_column(
        enum_type(CaptionStyle).evaluates_none(), default=DEFAULT_CAPTION_STYLE
    )

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    media_assets: Mapped[List["MediaAsset"]] = relationship(
        back_populates="project", cascade=DB_DELETE_ORPHAN_CASCADE, passive_deletes=True
    )
    clips: Mapped[List["Clip"]] = relationship(
        back_populates="project",
        cascade=DB_DELETE_ORPHAN_CASCADE,
        passive_deletes=True,
        order_by="(Clip.position, Clip.created_at)",
    )
    documents: Mapped[List["ProjectDocument"]] = relationship(
        back_populates="project",
        cascade=DB_DELETE_ORPHAN_CASCADE,
        passive_deletes=True,
        order_by="ProjectDocument.created_at",
    )