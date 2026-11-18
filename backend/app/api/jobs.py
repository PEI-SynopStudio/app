from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import JOB_ROUTE, JOBS_ROUTE_TAG, PROJECTS_ROUTE_PREFIX
from app.database.session import get_db
from app.schemas.job import JobStatusResponseSchema
from app.services.workflow.jobs import get_job

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[JOBS_ROUTE_TAG])


# Return the current state of one job: progress, result or failure details.
# Source: T3.13 job status; MS2 FR02 – Outputs (progress).
@router.get(JOB_ROUTE, response_model=JobStatusResponseSchema)
def read_job(project_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        return get_job(db, project_id, job_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
