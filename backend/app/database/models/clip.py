import uuid
from datetime import datetime
from typing import Dict, List, Optional


from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import CLIP_TITLE_MAX_LENGTH, DB_ON_DELETE_CASCADE, FK_PROJECT_ID, TABLE_CLIPS, Language
from app.database.base import Base, enum_type, utc_now


class Clip(Base):
    """A short clip cut from the project's video

    The scenes are parts of the original video, in seconds and in the order they play in the clip,
    so every clip stays traceable to its exact position in the recording
    """

    __tablename__ = TABLE_CLIPS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_PROJECT_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    title: Mapped[str] = mapped_column(String(CLIP_TITLE_MAX_LENGTH))
    # [{"start": 312.0, "end": 326.0}, ...]; always replaced as a whole, so the change is detected.
    scenes: Mapped[List[Dict[str, float]]] = mapped_column(JSONB)
    # None = the language spoken in the video (Project.language).
    subtitle_language: Mapped[Optional[Language]] = mapped_column(enum_type(Language))
    # Order of the clip in its project; new clips go to the end.
    position: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    project: Mapped["Project"] = relationship(back_populates="clips")