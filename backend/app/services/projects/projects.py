import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_DETAIL_CHANGES,
    AUDIT_LICENCE_FIELDS,
    AUDIT_PROJECT_FIELDS,
    ERROR_INVALID_PROJECT_ID,
    ERROR_LICENCE_NOT_CONFIRMED,
    ERROR_PROJECT_BUSY,
    ERROR_PROJECT_NOT_FOUND,
    JOB_ACTIVE_STATUSES,
    JSON_DUMP_MODE,
    PROJECT_LIST_DEFAULT_LIMIT,
    PROJECT_LIST_MIN_OFFSET,
    AuditAction,
    ProjectStatus,
)
from app.database.models import Clip, Job, Project
from app.schemas.project import ProjectCreate, ProjectPage, ProjectSummary, ProjectUpdate
from app.services.audit.audit import record_audit
from app.services.storage.local import LocalStorage
from app.services.storage.object_storage import ObjectStorage


class ProjectNotFoundError(LookupError):
    pass


class LicenceNotConfirmedError(PermissionError):
    pass


class ProjectBusyError(Exception):
    pass


# Register a project with its authorship and licensing metadata, and record it in the audit log.
# Source: MS2 FR01 – Inputs and Output (persisted project record with compliance metadata); FR09; FR18.
def create_project(db: Session, data: ProjectCreate, owner_id: Optional[str] = None) -> Project:
    """owner_id stays None until authentication exists (T3.11)."""
    project = Project(**data.model_dump(), owner_id=owner_id)
    db.add(project)
    db.flush()  # assigns the ID the audit entries refer to
    record_audit(
        db, project.id, AuditAction.PROJECT_CREATED, data.model_dump(mode=JSON_DUMP_MODE, include=AUDIT_PROJECT_FIELDS)
    )
    if project.licence_confirmed and project.authorship_confirmed:
        record_audit(
            db,
            project.id,
            AuditAction.LICENCE_CONFIRMED,
            data.model_dump(mode=JSON_DUMP_MODE, include=AUDIT_LICENCE_FIELDS),
        )
    db.commit()
    return project


def get_project(db: Session, project_id: str, owner_id: Optional[str] = None) -> Project:
    """With an owner_id, another user's project is reported as not found, so its existence is not revealed."""
    project = db.get(Project, _parse_project_id(project_id))
    if project is None or (owner_id is not None and project.owner_id != owner_id):
        raise ProjectNotFoundError(ERROR_PROJECT_NOT_FOUND.format(project_id=project_id))
    return project


# List the project library, most recently changed first, with search by title and pagination.
# Source: frontend project library (search and filters); US34 (projects the user can delete).
def list_projects(
    db: Session,
    *,
    owner_id: Optional[str] = None,
    query: Optional[str] = None,
    status: Optional[ProjectStatus] = None,
    limit: int = PROJECT_LIST_DEFAULT_LIMIT,
    offset: int = PROJECT_LIST_MIN_OFFSET,
) -> ProjectPage:
    filters = []
    if owner_id is not None:
        filters.append(Project.owner_id == owner_id)
    if status is not None:
        filters.append(Project.status == status)
    if query and query.strip():
        # autoescape: "%" and "_" typed by the user are searched literally.
        filters.append(Project.title.icontains(query.strip(), autoescape=True))

    total = db.scalar(select(func.count()).select_from(Project).where(*filters))
    clip_count = select(func.count(Clip.id)).where(Clip.project_id == Project.id).scalar_subquery()
    rows = db.execute(
        select(Project, clip_count)
        .where(*filters)
        .order_by(Project.updated_at.desc(), Project.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [ProjectSummary.model_validate(project).model_copy(update={"clip_count": count}) for project, count in rows]
    return ProjectPage(items=items, total=total, limit=limit, offset=offset)


# Change the title, the prompt or the output settings of a project; each change is kept in the audit log.
# Source: MS2 FR09 (output configuration); FR18 (every manual alteration is recorded).
def update_project(db: Session, project_id: str, data: ProjectUpdate, owner_id: Optional[str] = None) -> Project:
    project = get_project(db, project_id, owner_id)
    changed = {
        field for field, value in data.model_dump(exclude_unset=True).items() if getattr(project, field) != value
    }
    if changed:
        for field in changed:
            setattr(project, field, getattr(data, field))
        record_audit(
            db,
            project.id,
            AuditAction.PROJECT_UPDATED,
            {AUDIT_DETAIL_CHANGES: data.model_dump(mode=JSON_DUMP_MODE, include=changed)},
        )
        db.commit()
    return project


def require_ingestion_allowed(db: Session, project_id: str) -> Project:
    """The AI pipeline must never start without a confirmed licence and authorship"""
    project = get_project(db, project_id)
    if not (project.licence_confirmed and project.authorship_confirmed):
        raise LicenceNotConfirmedError(ERROR_LICENCE_NOT_CONFIRMED)
    return project


# Delete a project with its videos, documents, clips, jobs and uploads; only the audit records remain.
# Source: US34; MS3 §1.4.3 (project deletion, licence and editorial records kept for 12 months); FR18.
def delete_project(db: Session, storage: LocalStorage, object_storage: ObjectStorage, project_id: str) -> None:
    """Refused while a job is active, because its worker would keep writing files for the project.

    The objects go first: if the storage fails, the project stays and the deletion can be repeated,
    instead of leaving videos that nothing refers to any more.
    """
    project = get_project(db, project_id)
    active = select(Job.id).where(Job.project_id == project.id, Job.status.in_(JOB_ACTIVE_STATUSES)).limit(1)
    if db.scalar(active) is not None:
        raise ProjectBusyError(ERROR_PROJECT_BUSY.format(project_id=project_id))
    object_storage.delete_project(project_id)
    record_audit(
        db, project.id, AuditAction.PROJECT_DELETED, {field: getattr(project, field) for field in AUDIT_PROJECT_FIELDS}
    )
    db.delete(project)
    db.commit()
    storage.delete_project(project_id)


def _parse_project_id(project_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_PROJECT_ID.format(project_id=project_id))