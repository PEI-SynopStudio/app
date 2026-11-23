import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_CLIP_FIELDS,
    AUDIT_DETAIL_CHANGES,
    AUDIT_DETAIL_CLIP_ID,
    ERROR_CLIP_NOT_FOUND,
    ERROR_INVALID_CLIP_ID,
    FIRST_CLIP_POSITION,
    JSON_DUMP_MODE,
    AuditAction,
)
from app.database.base import utc_now
from app.database.models import Clip, Project
from app.schemas.clip import ClipCreate, ClipUpdate
from app.services.audit.audit import record_audit
from app.services.projects.projects import get_project


class ClipNotFoundError(LookupError):
    pass


def list_clips(db: Session, project_id: str, owner_id: Optional[str] = None) -> List[Clip]:
    """The clips of a project in their order."""
    return list(get_project(db, project_id, owner_id).clips)


def get_clip(db: Session, project_id: str, clip_id: str, owner_id: Optional[str] = None) -> Clip:
    return _find_clip(db, get_project(db, project_id, owner_id), clip_id)


# Add a clip made of parts of the original video; it goes to the end of the project's list.
# Source: MS2 FR10 (clip proposals), FR11 (link to the source position), FR12 (editing); FR18 (audit).
def create_clip(db: Session, project_id: str, data: ClipCreate, owner_id: Optional[str] = None) -> Clip:
    project = get_project(db, project_id, owner_id)
    last = db.scalar(select(func.max(Clip.position)).where(Clip.project_id == project.id))
    clip = Clip(
        project_id=project.id,
        title=data.title,
        scenes=[scene.model_dump() for scene in data.scenes],
        subtitle_language=data.subtitle_language,
        position=FIRST_CLIP_POSITION if last is None else last + 1,
    )
    db.add(clip)
    db.flush()  # assigns the ID the audit entry refers to
    record_audit(
        db, project.id, AuditAction.CLIP_CREATED, {AUDIT_DETAIL_CLIP_ID: str(clip.id), **data.model_dump(mode=JSON_DUMP_MODE)}
    )
    _touch(project)
    db.commit()
    return clip


# Rename a clip, change its scenes (trim, reorder, remove) or the language of its subtitles.
# Source: MS2 FR12, US21 (adjust start and end points, reorder or reject segments); FR18, US30 (history of changes).
def update_clip(
    db: Session, project_id: str, clip_id: str, data: ClipUpdate, owner_id: Optional[str] = None
) -> Clip:
    project = get_project(db, project_id, owner_id)
    clip = _find_clip(db, project, clip_id)
    values = data.model_dump(exclude_unset=True)
    changed = {field for field, value in values.items() if getattr(clip, field) != value}
    if changed:
        for field in changed:
            # The scenes are replaced by a new list, so the JSONB column is saved.
            setattr(clip, field, values[field])
        record_audit(
            db,
            project.id,
            AuditAction.CLIP_UPDATED,
            {AUDIT_DETAIL_CLIP_ID: str(clip.id), AUDIT_DETAIL_CHANGES: data.model_dump(mode=JSON_DUMP_MODE, include=changed)},
        )
        _touch(project)
        db.commit()
    return clip


# Delete a clip; the audit log keeps its title and scenes.
# Source: MS2 FR18, US30 (history of the editorial decisions of each clip).
def delete_clip(db: Session, project_id: str, clip_id: str, owner_id: Optional[str] = None) -> None:
    project = get_project(db, project_id, owner_id)
    clip = _find_clip(db, project, clip_id)
    record_audit(
        db,
        project.id,
        AuditAction.CLIP_DELETED,
        {AUDIT_DETAIL_CLIP_ID: str(clip.id), **{field: getattr(clip, field) for field in AUDIT_CLIP_FIELDS}},
    )
    db.delete(clip)
    _touch(project)
    db.commit()


def _find_clip(db: Session, project: Project, clip_id: str) -> Clip:
    """A clip of another project is reported as not found."""
    clip = db.get(Clip, _parse_clip_id(clip_id))
    if clip is None or clip.project_id != project.id:
        raise ClipNotFoundError(ERROR_CLIP_NOT_FOUND.format(clip_id=clip_id))
    return clip


def _touch(project: Project) -> None:
    """A change to a clip is a change to the project: the library lists the most recent first."""
    project.updated_at = utc_now()


def _parse_clip_id(clip_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(clip_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_CLIP_ID.format(clip_id=clip_id))