from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

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
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectPage, ProjectResponse, ProjectUpdate
from app.services.projects.projects import create_project, delete_project, get_project, list_projects, update_project
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[PROJECTS_ROUTE_TAG])

# TODO(auth): once authentication exists, pass the user's ID as owner_id to every service call,
# so each user only sees and changes their own projects.


# Create a project with the metadata required before any processing and the settings of its clips.
# Source: MS2 FR01 – Inputs and Business Rules; FR09 (output configuration).
@router.post(ROUTE_ROOT, status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create(body: ProjectCreate, db: Session = Depends(get_db)):
    return ProjectResponse.model_validate(create_project(db, body))


# List the project library: search by title, filter by status, most recently changed first.
@router.get(ROUTE_ROOT, response_model=ProjectPage)
def read_all(
    q: Optional[str] = Query(default=None, max_length=PROJECT_TITLE_MAX_LENGTH),
    status_filter: Optional[ProjectStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=PROJECT_LIST_DEFAULT_LIMIT, ge=PROJECT_LIST_MIN_LIMIT, le=PROJECT_LIST_MAX_LIMIT),
    offset: int = Query(default=PROJECT_LIST_MIN_OFFSET, ge=PROJECT_LIST_MIN_OFFSET),
    db: Session = Depends(get_db),
):
    return list_projects(db, query=q, status=status_filter, limit=limit, offset=offset)


# Return a project with its clips and supporting documents.
@router.get(PROJECT_ID_ROUTE, response_model=ProjectResponse)
def read(project_id: str, db: Session = Depends(get_db)):
    try:
        return ProjectResponse.model_validate(get_project(db, project_id))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Change the title, the prompt, the format, the spoken language or the subtitles of a project.
# Source: MS2 FR09; FR18 (every change is recorded in the audit log).
@router.patch(PROJECT_ID_ROUTE, response_model=ProjectResponse)
def update(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    try:
        return ProjectResponse.model_validate(update_project(db, project_id, body))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Delete a project and all its data; the licence and editorial audit records are kept.
# Source: US34; MS3 §1.4.3.
@router.delete(PROJECT_ID_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: str,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    object_storage: ObjectStorage = Depends(get_object_storage),
):
    try:
        delete_project(db, storage, object_storage, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc