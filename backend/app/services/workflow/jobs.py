import logging
import uuid
from dataclasses import fields
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_DETAIL_JOB_ID,
    AUDIT_DETAIL_SOURCE,
    ERROR_INGESTION_ALREADY_RUNNING,
    JOB_ACTIVE_INGESTION_INDEX,
    JSON_DUMP_MODE,
    LOG_JOB_EVENT_REJECTED,
    ApplyOutcome,
    AuditAction,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobTypeEnum,
)
from app.core.exceptions import JobNotFoundError
from app.database.base import utc_now
from app.database.models import Job
from app.schemas.job import IngestionParams, JobUpdateEventSchema
from app.services.audit.audit import record_audit
from app.services.projects.projects import require_ingestion_allowed
from app.services.workflow.state_machine import ApplyResult, JobSnapshot, apply_event, change_status

logger = logging.getLogger(__name__)


class IngestionAlreadyRunningError(Exception):
    pass


# Create the job; the licence check, the one-active-job rule and the audit entry share one transaction.
# Source: MS2 FR01 – Acceptance Criteria; FR02 – Outputs (asynchronous processing); FR18.
def create_ingestion_job(
    db: Session,
    project_id: str,
    params: IngestionParams,
    source: str,
    media_asset_id: Optional[uuid.UUID] = None,
) -> Job:
    """Raises IngestionAlreadyRunningError when the project already has an active ingestion."""
    project = require_ingestion_allowed(db, project_id)
    job = Job(
        project_id=project.id,
        media_asset_id=media_asset_id,
        job_type=JobTypeEnum.INGESTION,
        parameters=params.model_dump(mode=JSON_DUMP_MODE),
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if exc.orig.diag.constraint_name == JOB_ACTIVE_INGESTION_INDEX:
            raise IngestionAlreadyRunningError(
                ERROR_INGESTION_ALREADY_RUNNING.format(project_id=project_id)
            ) from exc
        raise
    record_audit(
        db,
        project.id,
        AuditAction.INGESTION_REQUESTED,
        {AUDIT_DETAIL_JOB_ID: str(job.id), AUDIT_DETAIL_SOURCE: source},
    )
    db.commit()
    return job


def queue_job(db: Session, job: Job) -> Job:
    """Committed before publishing, so a worker event never arrives while the job is still pending."""
    return _change_status(db, job, JobStatusEnum.QUEUED)


def fail_job(db: Session, job: Job, error_code: JobErrorCodeEnum, error_message: str) -> Job:
    return _change_status(db, job, JobStatusEnum.FAILED, error_code, error_message)


# Apply a worker event to the stored job, one event at a time per job.
# Source: architecture §2 (workers publish results, the backend persists them); T3.13 job state machine.
def apply_job_event(db: Session, event: JobUpdateEventSchema) -> ApplyResult:
    """The row lock makes concurrent events of the same job wait for each other."""
    job = db.get(Job, event.job_id, with_for_update=True)
    if job is None:
        raise JobNotFoundError()

    result = apply_event(_snapshot(job), event)
    if result.outcome == ApplyOutcome.APPLIED:
        _store(job, result.job)
    elif result.outcome == ApplyOutcome.REJECTED:
        logger.warning(LOG_JOB_EVENT_REJECTED, event.job_id, result.reason)
    db.commit()
    return result


def _change_status(
    db: Session,
    job: Job,
    target: JobStatusEnum,
    error_code: Optional[JobErrorCodeEnum] = None,
    error_message: Optional[str] = None,
) -> Job:
    _store(job, change_status(_snapshot(job), target, utc_now(), error_code, error_message))
    db.commit()
    return job


def _snapshot(job: Job) -> JobSnapshot:
    return JobSnapshot(**{field.name: getattr(job, field.name) for field in fields(JobSnapshot)})


def _store(job: Job, snapshot: JobSnapshot) -> None:
    for field in fields(JobSnapshot):
        setattr(job, field.name, getattr(snapshot, field.name))
