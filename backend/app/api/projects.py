# Temporary project endpoints until FR01 is implemented.
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import (
    PROJECT_ID_ROUTE,
    PROJECT_TITLE_MAX_LENGTH,
    PROJECT_TITLE_MIN_LENGTH,
    PROJECTS_ROUTE_PREFIX,
    PROJECTS_ROUTE_TAG,
    ROUTE_ROOT,
)
from app.services.projects.projects import Project, ProjectNotFoundError, create_project, get_project
from app.services.storage.local import LocalStorage, get_storage

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[PROJECTS_ROUTE_TAG])


class ProjectCreate(BaseModel):
    title: str = Field(min_length=PROJECT_TITLE_MIN_LENGTH, max_length=PROJECT_TITLE_MAX_LENGTH)
    licence_confirmed: bool
    authorship_confirmed: bool


@router.post(ROUTE_ROOT, status_code=status.HTTP_201_CREATED, response_model=Project)
def create(body: ProjectCreate, storage: LocalStorage = Depends(get_storage)):
    return create_project(storage, body.title, body.licence_confirmed, body.authorship_confirmed)


@router.get(PROJECT_ID_ROUTE, response_model=Project)
def read(project_id: str, storage: LocalStorage = Depends(get_storage)):
    try:
        return get_project(storage, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
