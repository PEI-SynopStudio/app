import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    DB_DELETE_ORPHAN_CASCADE,
    OWNER_ID_MAX_LENGTH,
    PROJECT_AUTHOR_MAX_LENGTH,
    PROJECT_TITLE_MAX_LENGTH,
    TABLE_PROJECTS,
    LicenseType,
    ProjectStatus,
)
from app.database.base import Base, enum_type, utc_now


class Project(Base):
    """A recording with its authorship and licensing metadata (FR01)."""

    __tablename__ = TABLE_PROJECTS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Keycloak subject; stays empty until authentication exists (T3.11).
    owner_id: Mapped[Optional[str]] = mapped_column(String(OWNER_ID_MAX_LENGTH), index=True)
    title: Mapped[str] = mapped_column(String(PROJECT_TITLE_MAX_LENGTH))
    author: Mapped[str] = mapped_column(String(PROJECT_AUTHOR_MAX_LENGTH))
    speakers: Mapped[List[str]] = mapped_column(JSONB, default=list)
    recording_date: Mapped[date]
    license_type: Mapped[LicenseType] = mapped_column(enum_type(LicenseType))
    copyright_notice: Mapped[str] = mapped_column(Text)
    licence_confirmed: Mapped[bool]
    authorship_confirmed: Mapped[bool]
    status: Mapped[ProjectStatus] = mapped_column(enum_type(ProjectStatus), default=ProjectStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    media_assets: Mapped[List["MediaAsset"]] = relationship(
        back_populates="project", cascade=DB_DELETE_ORPHAN_CASCADE, passive_deletes=True
    )
