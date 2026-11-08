from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import PROJECT_ID_ROUTE, PROJECTS_ROUTE_PREFIX, PROJECTS_ROUTE_TAG, ROUTE_ROOT
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectResponse
from app.services.projects.projects import create_project, get_project

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[PROJECTS_ROUTE_TAG])


# Create a project with the metadata required before any processing.
# Source: MS2 FR01 – Inputs and Business Rules.
@router.post(ROUTE_ROOT, status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create(body: ProjectCreate, db: Session = Depends(get_db)):
    return create_project(db, body)


@router.get(PROJECT_ID_ROUTE, response_model=ProjectResponse)
def read(project_id: str, db: Session = Depends(get_db)):
    try:
        return get_project(db, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
