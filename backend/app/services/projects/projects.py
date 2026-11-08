import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_LICENCE_FIELDS,
    AUDIT_PROJECT_FIELDS,
    ERROR_INVALID_PROJECT_ID,
    ERROR_LICENCE_NOT_CONFIRMED,
    ERROR_PROJECT_BUSY,
    ERROR_PROJECT_NOT_FOUND,
    JOB_ACTIVE_STATUSES,
    JSON_DUMP_MODE,
    AuditAction,
)
from app.database.models import Job, Project
from app.schemas.project import ProjectCreate
from app.services.audit.audit import record_audit
from app.services.storage.local import LocalStorage


class ProjectNotFoundError(LookupError):
    pass


class LicenceNotConfirmedError(PermissionError):
    pass


class ProjectBusyError(Exception):
    pass


# Register a project with its authorship and licensing metadata, and record it in the audit log.
# Source: MS2 FR01 – Inputs and Output (persisted project record with compliance metadata); FR18.
def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
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


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, _parse_project_id(project_id))
    if project is None:
        raise ProjectNotFoundError(ERROR_PROJECT_NOT_FOUND.format(project_id=project_id))
    return project


def require_ingestion_allowed(db: Session, project_id: str) -> Project:
    """The AI pipeline must never start without a confirmed licence and authorship (FR01)."""
    project = get_project(db, project_id)
    if not (project.licence_confirmed and project.authorship_confirmed):
        raise LicenceNotConfirmedError(ERROR_LICENCE_NOT_CONFIRMED)
    return project


# Delete a project with its videos, jobs and uploads; only the audit records remain.
# Source: US34; MS3 §1.4.3 (project deletion, licence and editorial records kept for 12 months); FR18.
def delete_project(db: Session, storage: LocalStorage, project_id: str) -> None:
    """Refused while a job is active, because its worker would keep writing files for the project."""
    project = get_project(db, project_id)
    active = select(Job.id).where(Job.project_id == project.id, Job.status.in_(JOB_ACTIVE_STATUSES)).limit(1)
    if db.scalar(active) is not None:
        raise ProjectBusyError(ERROR_PROJECT_BUSY.format(project_id=project_id))
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
