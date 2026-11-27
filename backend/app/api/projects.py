from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_project_access
from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    PROJECT_ID_ROUTE,
    PROJECT_LIST_DEFAULT_LIMIT,
    PROJECT_LIST_MAX_LIMIT,
    PROJECT_LIST_MIN_LIMIT,
    PROJECT_LIST_MIN_OFFSET,
    PROJECT_TITLE_MAX_LENGTH,
    PROJECTS_ROUTE_PREFIX,
    PROJECTS_ROUTE_TAG,
    ROUTE_ROOT,
    ProjectStatus,
)
from app.database.models import Project, User
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectPage, ProjectResponse, ProjectUpdate
from app.services.projects.projects import create_project, delete_project, list_library, update_project
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[PROJECTS_ROUTE_TAG])

# Every route needs a signed-in user. A project belongs to the user who created it; for anyone else
# it answers 404, like a missing one, so its existence is not revealed (MS3 §1.1.6).


# Create a project with the metadata required before any processing and the settings of its clips;
# the signed-in user owns it.
# Source: MS2 FR01 – Inputs and Business Rules; FR09 (output configuration); MS3 §1.1.6 (access control).
@router.post(ROUTE_ROOT, status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create(body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ProjectResponse.model_validate(create_project(db, body, user))


# List the signed-in user's project library: search by title, filter by status, most recently changed first.
@router.get(ROUTE_ROOT, response_model=ProjectPage)
def read_all(
    q: Optional[str] = Query(default=None, max_length=PROJECT_TITLE_MAX_LENGTH),
    status_filter: Optional[ProjectStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=PROJECT_LIST_DEFAULT_LIMIT, ge=PROJECT_LIST_MIN_LIMIT, le=PROJECT_LIST_MAX_LIMIT),
    offset: int = Query(default=PROJECT_LIST_MIN_OFFSET, ge=PROJECT_LIST_MIN_OFFSET),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_library(db, user, query=q, status=status_filter, limit=limit, offset=offset)


# Return a project with its clips and supporting documents.
@router.get(PROJECT_ID_ROUTE, response_model=ProjectResponse)
def read(project: Project = Depends(require_project_access)):
    return ProjectResponse.model_validate(project)


# Change the title, the prompt, the format, the spoken language or the subtitles of a project.
# Source: MS2 FR09; FR18 (every change is recorded in the audit log, with who made it).
@router.patch(PROJECT_ID_ROUTE, response_model=ProjectResponse, dependencies=[Depends(require_project_access)])
def update(
    project_id: str,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return ProjectResponse.model_validate(update_project(db, project_id, body, actor=user))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Delete a project and all its data; the licence and editorial audit records are kept.
# Source: US34; MS3 §1.4.3.
@router.delete(
    PROJECT_ID_ROUTE, status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_project_access)]
)
def delete(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    object_storage: ObjectStorage = Depends(get_object_storage),
):
    try:
        delete_project(db, storage, object_storage, project_id, actor=user)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc