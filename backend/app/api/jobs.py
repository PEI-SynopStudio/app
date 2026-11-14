from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import JOB_ROUTE, JOBS_ROUTE_TAG, PROJECTS_ROUTE_PREFIX, JOB_CANCEL_ROUTE, PROJECT_JOB_ROUTE
from app.database.session import get_db
from app.schemas.job import JobStatusResponseSchema
from app.services.projects.projects import get_project
from app.services.workflow.jobs import get_job, cancel_job, list_project_jobs
from app.services.workflow.progress_hub import JobProgressHub, get_progress_hub

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[JOBS_ROUTE_TAG])

@router.get(PROJECT_JOB_ROUTE, response_model=List[JobStatusResponseSchema])
def read_project_jobs(project_id: str, db: Session = Depends(get_db)):
    try:
        project = get_project(db, project_id)
        return list_project_jobs(db, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc



# Return the current state of one job: progress, result or failure details.
# Source: T3.13 job status; MS2 FR02 – Outputs (progress).
@router.get(JOB_ROUTE, response_model=JobStatusResponseSchema)
def read_job(project_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        return get_job(db, project_id, job_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Cancel an active job and notify the clients
@router.post(JOB_CANCEL_ROUTE, response_model=JobStatusResponseSchema)
def cancels_job(project_id: str, job_id: str, db: Session = Depends(get_db), hub: JobProgressHub = Depends(get_progress_hub)):
    try:
        job = cancel_job(db, project_id, job_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    
    response = JobStatusResponseSchema.model_validate(job)
    hub.publish(response)
    return response