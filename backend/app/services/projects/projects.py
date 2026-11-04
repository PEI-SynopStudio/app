# Temporary project store until FR01 (project management) is implemented.
# It only keeps what FR02 needs: a project ID and the licence/authorship confirmation.
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from app.core.config import (
    ERROR_LICENCE_NOT_CONFIRMED,
    ERROR_PROJECT_NOT_FOUND,
    JSON_DUMP_MODE,
    PROJECT_FILE,
)
from app.services.storage.local import LocalStorage


class Project(BaseModel):
    id: str
    title: str
    licence_confirmed: bool
    authorship_confirmed: bool
    created_at: datetime


class ProjectNotFoundError(LookupError):
    pass


class LicenceNotConfirmedError(PermissionError):
    pass


def create_project(
    storage: LocalStorage,
    title: str,
    licence_confirmed: bool,
    authorship_confirmed: bool,
) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        title=title,
        licence_confirmed=licence_confirmed,
        authorship_confirmed=authorship_confirmed,
        created_at=datetime.now(timezone.utc),
    )
    storage.write_json(project.id, PROJECT_FILE, project.model_dump(mode=JSON_DUMP_MODE))
    return project


def get_project(storage: LocalStorage, project_id: str) -> Project:
    data = storage.read_json(project_id, PROJECT_FILE)
    if data is None:
        raise ProjectNotFoundError(ERROR_PROJECT_NOT_FOUND.format(project_id=project_id))
    return Project.model_validate(data)


def require_ingestion_allowed(storage: LocalStorage, project_id: str) -> Project:
    """The AI pipeline must never start without a confirmed licence and authorship (FR01)."""
    project = get_project(storage, project_id)
    if not (project.licence_confirmed and project.authorship_confirmed):
        raise LicenceNotConfirmedError(ERROR_LICENCE_NOT_CONFIRMED)
    return project
