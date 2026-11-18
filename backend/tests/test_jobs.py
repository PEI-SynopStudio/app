import threading
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.config import (
    ApplyOutcome,
    AuditAction,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    LicenseType,
)
from app.core.exceptions import InvalidStateTransitionError, JobNotFoundError
from app.database.models import AuditLog, Job
from app.schemas.job import IngestionParams, JobUpdateEventSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import LicenceNotConfirmedError, ProjectNotFoundError, create_project
from app.services.workflow.jobs import (
    IngestionAlreadyRunningError,
    apply_job_event,
    create_ingestion_job,
    fail_job,
    queue_job,
)

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
THREAD_WAIT_SECONDS = 0.5
THREAD_TIMEOUT_SECONDS = 10


def make_project(db, licence=True):
    return str(create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=licence,
        authorship_confirmed=True,
    )).id)


def new_job(db, project_id):
    return create_ingestion_job(db, project_id, IngestionParams(source_url=SAMPLE_URL), SAMPLE_URL)


def queued_job(db):
    return queue_job(db, new_job(db, make_project(db)))


def event_for(job, **kwargs):
    kwargs.setdefault("status", JobStatusEnum.PROCESSING)
    kwargs.setdefault("step", JobStepProcessingEnum.DOWNLOADING_MEDIA)
    kwargs.setdefault("step_progress", 50)
    return JobUpdateEventSchema(job_id=job.id, **kwargs)


def test_a_new_job_is_pending_and_audited(db):
    project_id = make_project(db)

    job = new_job(db, project_id)

    assert job.status == JobStatusEnum.PENDING
    assert job.parameters["source_url"] == SAMPLE_URL
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.INGESTION_REQUESTED))
    assert entry.details == {"job_id": str(job.id), "source": SAMPLE_URL}


def test_a_job_needs_a_confirmed_licence(db):
    project_id = make_project(db, licence=False)

    with pytest.raises(LicenceNotConfirmedError):
        new_job(db, project_id)
    assert db.scalar(select(Job)) is None


def test_a_job_needs_an_existing_project(db):
    with pytest.raises(ProjectNotFoundError):
        new_job(db, str(uuid.uuid4()))


def test_a_second_active_ingestion_is_refused(db):
    project_id = make_project(db)
    new_job(db, project_id)

    with pytest.raises(IngestionAlreadyRunningError):
        new_job(db, project_id)


def test_a_failed_ingestion_can_be_repeated(db):
    project_id = make_project(db)
    fail_job(db, new_job(db, project_id), JobErrorCodeEnum.INTERNAL_ERROR, "Broker unavailable")

    assert new_job(db, project_id).status == JobStatusEnum.PENDING


def test_a_job_cannot_be_queued_twice(db):
    job = queued_job(db)

    with pytest.raises(InvalidStateTransitionError):
        queue_job(db, job)


def test_fail_job_keeps_the_error_details(db):
    job = fail_job(db, new_job(db, make_project(db)), JobErrorCodeEnum.INTERNAL_ERROR, "Broker unavailable")

    assert (job.status, job.error_code, job.error_message) == (
        JobStatusEnum.FAILED, JobErrorCodeEnum.INTERNAL_ERROR, "Broker unavailable"
    )
    assert job.finished_at is not None


def test_a_worker_event_updates_the_stored_job(db):
    job = queued_job(db)

    result = apply_job_event(db, event_for(job))

    db.expire_all()
    stored = db.get(Job, job.id)
    assert result.outcome == ApplyOutcome.APPLIED
    assert (stored.status, stored.step, stored.step_progress) == (
        JobStatusEnum.PROCESSING, JobStepProcessingEnum.DOWNLOADING_MEDIA, 50
    )
    assert stored.progress == 25
    assert stored.started_at is not None


def test_a_repeated_event_changes_nothing(db):
    job = queued_job(db)
    apply_job_event(db, event_for(job))

    assert apply_job_event(db, event_for(job)).outcome == ApplyOutcome.IGNORED


def test_a_completed_event_stores_the_output(db):
    job = queued_job(db)
    apply_job_event(db, event_for(job))

    apply_job_event(db, event_for(job, status=JobStatusEnum.COMPLETED, step=None, step_progress=100, output={"a": 1}))

    db.expire_all()
    stored = db.get(Job, job.id)
    assert (stored.status, stored.progress, stored.output) == (JobStatusEnum.COMPLETED, 100, {"a": 1})


def test_an_event_of_an_unknown_job_is_refused(db):
    event = JobUpdateEventSchema(job_id=uuid.uuid4(), status=JobStatusEnum.PROCESSING, step_progress=0)

    with pytest.raises(JobNotFoundError):
        apply_job_event(db, event)


def test_events_of_the_same_job_wait_for_each_other(db, session_factory):
    job = queued_job(db)
    db.get(Job, job.id, with_for_update=True)  # holds the row lock

    def apply_in_another_session():
        with session_factory() as other:
            apply_job_event(other, event_for(job))

    thread = threading.Thread(target=apply_in_another_session)
    thread.start()
    thread.join(THREAD_WAIT_SECONDS)
    assert thread.is_alive()

    db.commit()
    thread.join(THREAD_TIMEOUT_SECONDS)
    assert not thread.is_alive()
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatusEnum.PROCESSING
