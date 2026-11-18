from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_project_access
from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import PROJECT_ID_ROUTE, PROJECTS_ROUTE_PREFIX, PROJECTS_ROUTE_TAG, ROUTE_ROOT
from app.database.models import Project, User
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectResponse
from app.services.projects.projects import create_project, delete_project, list_projects
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[PROJECTS_ROUTE_TAG])


# Create a project with the metadata required before any processing; the signed-in user owns it.
# Source: MS2 FR01 – Inputs and Business Rules; MS3 §1.1.6 (access control).
@router.post(ROUTE_ROOT, status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create(body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_project(db, body, user)


@router.get(ROUTE_ROOT, response_model=List[ProjectResponse])
def list_own(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_projects(db, user)


@router.get(PROJECT_ID_ROUTE, response_model=ProjectResponse)
def read(project: Project = Depends(require_project_access)):
    return project


# Delete a project and all its data; the licence and editorial audit records are kept.
# Source: US34; MS3 §1.4.3.
@router.delete(
    PROJECT_ID_ROUTE, status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_project_access)]
)
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
