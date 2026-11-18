from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.dependencies import get_current_user_id
from app.schemas.project import (
    Project,
    ProjectCreate,
    ProjectLibrary,
    ProjectStatus,
    ProjectUpdate,
)
from app.services.projects.project_service import (
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

router = APIRouter(prefix="/projects", tags=["projects"])

UserId = Annotated[str, Depends(get_current_user_id)]
Service = Annotated[ProjectService, Depends(get_project_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found")


@router.post("", response_model=Project, status_code=201)
def create_project(data: ProjectCreate, user_id: UserId, service: Service):
    return service.create(user_id, data)


@router.get("", response_model=ProjectLibrary)
def get_library(
    user_id: UserId,
    service: Service,
    q: str | None = None,
    status: ProjectStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return service.library(user_id, status=status, query=q, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, user_id: UserId, service: Service):
    try:
        return service.get_for_owner(user_id, project_id)
    except ProjectNotFoundError:
        raise _not_found()


@router.patch("/{project_id}", response_model=Project)
def update_project(
    project_id: str, data: ProjectUpdate, user_id: UserId, service: Service
):
    try:
        return service.update(user_id, project_id, data)
    except ProjectNotFoundError:
        raise _not_found()


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, user_id: UserId, service: Service):
    try:
        service.delete(user_id, project_id)
    except ProjectNotFoundError:
        raise _not_found()
    return Response(status_code=204)