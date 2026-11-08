import uuid

from sqlalchemy.orm import Session

from app.core.config import ERROR_INVALID_PROJECT_ID, ERROR_LICENCE_NOT_CONFIRMED, ERROR_PROJECT_NOT_FOUND
from app.database.models import Project
from app.schemas.project import ProjectCreate


class ProjectNotFoundError(LookupError):
    pass


class LicenceNotConfirmedError(PermissionError):
    pass


# Register a project with its authorship and licensing metadata.
# Source: MS2 FR01 – Inputs and Output (persisted project record with compliance metadata).
def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
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


def _parse_project_id(project_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_PROJECT_ID.format(project_id=project_id))
