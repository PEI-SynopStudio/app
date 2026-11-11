from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.exceptions import InvalidStateTransitionError, JobAlreadyTerminalError
from app.schemas.enums import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.services.workflow import state_machine
from app.schemas.job import JobUpdateEventSchema

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def make_job(**kwargs) -> state_machine.JobSnapshot:
    kwargs.setdefault("job_type", JobTypeEnum.INGESTION)
    kwargs.setdefault("status", JobStatusEnum.QUEUED)
    return state_machine.JobSnapshot(**kwargs)


def make_event(**kwargs) -> JobUpdateEventSchema:
    kwargs.setdefault("job_id", uuid4())
    kwargs.setdefault("status", JobStatusEnum.PROCESSING)
    kwargs.setdefault("step_progress", 0.0)
    kwargs.setdefault("emitted_at", at(1))
    return JobUpdateEventSchema(**kwargs)


def make_failed_event(**kwargs) -> JobUpdateEventSchema:
    kwargs.setdefault("error_code", JobErrorCodeEnum.SOURCE_UNAVAILABLE)
    kwargs.setdefault("error_message", "404")
    return make_event(status=JobStatusEnum.FAILED, **kwargs)


def test_change_status_to_queued():
    job = make_job(status=JobStatusEnum.PENDING)
    event = make_event(status=JobStatusEnum.QUEUED, emitted_at=at(5))
    new_job = state_machine.change_status(job, event.status, event.emitted_at)
    assert new_job.status == JobStatusEnum.QUEUED
    assert new_job.started_at is None
    assert new_job.finished_at is None

def test_change_status_to_processing():
    job = make_job(status=JobStatusEnum.QUEUED, started_at=None)
    event = make_event(status=JobStatusEnum.PROCESSING, emitted_at=at(10))
    new_job = state_machine.change_status(job, event.status, event.emitted_at)
    assert new_job.status == JobStatusEnum.PROCESSING
    assert new_job.started_at == at(10)
    assert new_job.finished_at is None
    
def test_change_status_to_completed():
    job = make_job(status=JobStatusEnum.PROCESSING, started_at=at(10))
    event = make_event(status=JobStatusEnum.COMPLETED, emitted_at=at(20))
    new_job = state_machine.change_status(job, event.status, event.emitted_at)
    assert new_job.status == JobStatusEnum.COMPLETED
    assert new_job.started_at == at(10)
    assert new_job.finished_at == at(20)
    
def test_change_status_to_failed():
    job = make_job(status=JobStatusEnum.PROCESSING, started_at=at(10))
    event = make_failed_event(emitted_at=at(15))
    new_job = state_machine.change_status(job, event.status, event.emitted_at, error_code=event.error_code)
    assert new_job.status == JobStatusEnum.FAILED
    assert new_job.started_at == at(10)
    assert new_job.finished_at == at(15)
    assert new_job.error_code == JobErrorCodeEnum.SOURCE_UNAVAILABLE
    
    
def test_change_status_to_cancelled():
    job = make_job(status=JobStatusEnum.PROCESSING, started_at=at(10))
    event = make_event(status=JobStatusEnum.CANCELLED, emitted_at=at(12))
    new_job = state_machine.change_status(job, event.status, event.emitted_at)
    assert new_job.status == JobStatusEnum.CANCELLED
    assert new_job.started_at == at(10)
    assert new_job.finished_at == at(12)
    
def test_change_status_invalid_transition():
    job = make_job(status=JobStatusEnum.COMPLETED, started_at=at(10), finished_at=at(20))
    event = make_event(status=JobStatusEnum.PROCESSING, emitted_at=at(25))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
        
def test_change_status_to_same_status():
    job = make_job(status=JobStatusEnum.PROCESSING, started_at=at(10))
    event = make_event(status=JobStatusEnum.PROCESSING, emitted_at=at(15))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
def test_change_status_from_final_state():
    job = make_job(status=JobStatusEnum.COMPLETED, started_at=at(10), finished_at=at(20))
    event = make_event(status=JobStatusEnum.CANCELLED, emitted_at=at(25))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
def test_change_status_on_final_state():
    job = make_job(status=JobStatusEnum.FAILED, started_at=at(10), finished_at=at(20))
    event = make_event(status=JobStatusEnum.COMPLETED, emitted_at=at(25))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
def test_pending_cannot_start_processing():
    job = make_job(status=JobStatusEnum.PENDING)
    event = make_event(status=JobStatusEnum.PROCESSING, emitted_at=at(5))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)

def test_queued_cannot_complete():
    job = make_job(status=JobStatusEnum.QUEUED)
    event = make_event(status=JobStatusEnum.COMPLETED, emitted_at=at(5))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
        
def test_processing_cannot_queue():
    job = make_job(status=JobStatusEnum.PROCESSING)
    event = make_event(status=JobStatusEnum.QUEUED, emitted_at=at(5))
    with pytest.raises(InvalidStateTransitionError):
        state_machine.change_status(job, event.status, event.emitted_at)
        
        
def test_apply_event_does_not_mutate_input():
    job = make_job()
    state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.INITIALIZING, step_progress=50))

    assert job.status == JobStatusEnum.QUEUED
    assert job.progress == 0.0
    assert job.last_event_at is None
    
def test_started_at_is_not_overwritten():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INITIALIZING, started_at=at(0))
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.INITIALIZING, step_progress=50))

    assert result.job.started_at == at(0)
    
def test_progress_is_not_decreased():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INITIALIZING, progress=50.0)
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.INITIALIZING, step_progress=25))

    assert result.job.progress == 50.0
    
def test_progress_is_capped_at_99_while_processing():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.CLEANING_UP, progress=96.0)
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.CLEANING_UP, step_progress=100))

    assert result.job.progress == 99.0
    
def test_progress_is_100_when_completed():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.CLEANING_UP, progress=99.0)
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.CLEANING_UP, step_progress=100, status=JobStatusEnum.COMPLETED))

    assert result.job.progress == 100.0
    
def test_repeated_event_with_same_attempt_is_ignored():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INITIALIZING, step_progress=50, progress=2.5, attempt=1)
    event = make_event(step=JobStepProcessingEnum.INITIALIZING, step_progress=50, attempt=1)
    result = state_machine.apply_event(job, event)

    assert result.outcome == state_machine.ApplyOutcome.IGNORED
    
    
def test_newer_step_is_applied_and_resets_step_progress():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.DOWNLOADING_MEDIA, step_progress=100.0, progress=45.0)
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.INSPECTING_MEDIA, step_progress=0))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.step == JobStepProcessingEnum.INSPECTING_MEDIA
    assert result.job.step_progress == 0
    assert result.job.progress == 45.0


def test_newer_step_never_makes_global_progress_go_back():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INITIALIZING, step_progress=90.0, progress=30.0)
    result = state_machine.apply_event(job, make_event(step=JobStepProcessingEnum.DOWNLOADING_MEDIA, step_progress=0))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.step == JobStepProcessingEnum.DOWNLOADING_MEDIA
    assert result.job.step_progress == 0
    assert result.job.progress == 30.0
    
def test_completed_event():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.CLEANING_UP, step_progress=80.0, progress=98.0)
    result = state_machine.apply_event(job, make_event(status=JobStatusEnum.COMPLETED, step_progress=100, output={"duration": 12}))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.COMPLETED
    assert result.job.step == JobStepProcessingEnum.FINISHED
    assert result.job.step_progress == 100.0
    assert result.job.progress == 100.0
    assert result.job.output == {"duration": 12}
    assert result.job.finished_at == at(1)
    
def test_failed_event_keeps_progress_and_stores_error():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.DOWNLOADING_MEDIA, step_progress=50.0, progress=25.0)
    result = state_machine.apply_event(job, make_failed_event(step_progress=0))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.FAILED
    assert result.job.step == JobStepProcessingEnum.DOWNLOADING_MEDIA
    assert result.job.step_progress == 50.0
    assert result.job.progress == 25.0
    assert result.job.error_code == JobErrorCodeEnum.SOURCE_UNAVAILABLE
    assert result.job.error_message == "404"
    assert result.job.finished_at == at(1)
    
def test_failed_event_can_update_the_step_where_it_failed():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.INITIALIZING, progress=2.0)
    result = state_machine.apply_event(job, make_failed_event(step=JobStepProcessingEnum.DOWNLOADING_MEDIA))

    assert result.job.step == JobStepProcessingEnum.DOWNLOADING_MEDIA


def test_queued_job_can_fail_before_processing():
    result = state_machine.apply_event(make_job(), make_failed_event())

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.FAILED


def test_cancelled_event_from_worker():
    job = make_job(status=JobStatusEnum.PROCESSING, step=JobStepProcessingEnum.DOWNLOADING_MEDIA, step_progress=20.0, progress=13.0)
    result = state_machine.apply_event(job, make_event(status=JobStatusEnum.CANCELLED))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.CANCELLED
    assert result.job.progress == 13.0
    assert result.job.finished_at == at(1)
    
    
def test_cancelled_event_from_pending_job():
    result = state_machine.apply_event(make_job(status=JobStatusEnum.PENDING), make_event(status=JobStatusEnum.CANCELLED))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.CANCELLED
    assert result.job.finished_at == at(1)
    
def test_cancelled_event_from_queued_job():
    result = state_machine.apply_event(make_job(status=JobStatusEnum.QUEUED), make_event(status=JobStatusEnum.CANCELLED))

    assert result.outcome == state_machine.ApplyOutcome.APPLIED
    assert result.job.status == JobStatusEnum.CANCELLED
    assert result.job.finished_at == at(1)


def test_change_status_stores_error_message():
    job = make_job(status=JobStatusEnum.PROCESSING, started_at=at(10))
    new_job = state_machine.change_status(
        job, JobStatusEnum.FAILED, at(15), error_code=JobErrorCodeEnum.TIMEOUT, error_message="No events received"
    )

    assert new_job.error_message == "No events received"


def test_step_of_another_pipeline_is_rejected_with_a_clear_reason():
    result = state_machine.apply_event(make_job(), make_event(step=JobStepProcessingEnum.TRANSCRIBING))

    assert result.outcome == state_machine.ApplyOutcome.REJECTED
    assert "does not belong to pipeline" in result.reason
    

    
