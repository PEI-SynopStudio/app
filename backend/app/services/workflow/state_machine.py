from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.core.config import (
    ERROR_INVALID_TRANSITION,
    EVENT_IGNORED_EARLIER_STEP,
    EVENT_IGNORED_JOB_FINISHED,
    EVENT_IGNORED_LOWER_PROGRESS,
    EVENT_IGNORED_NO_CHANGE,
    EVENT_IGNORED_OUT_OF_ORDER,
    EVENT_IGNORED_PAST_ATTEMPT,
    EVENT_REJECTED_STATUS,
    EVENT_REJECTED_UNKNOWN_ATTEMPT,
    FIRST_JOB_ATTEMPT,
    PROGRESS_MAX,
    PROGRESS_MIN,
    WORKER_REPORTABLE_STATUSES,
    ApplyOutcome,
)
from app.core.exceptions import InvalidStepError
from app.schemas.enums import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.schemas.job import JobUpdateEventSchema
from app.services.workflow.progress import calculate_progress, get_step_weight
from app.services.workflow.transitions import can_transition, final_state, validate_transition


@dataclass(frozen=True)
class JobSnapshot:
    """The state of a job, independent of how it is stored."""
    job_type: JobTypeEnum
    status: JobStatusEnum = JobStatusEnum.PENDING
    step: JobStepProcessingEnum | None = None
    step_progress: float = PROGRESS_MIN
    progress: float = PROGRESS_MIN
    attempt: int = FIRST_JOB_ATTEMPT
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_event_at: datetime | None = None


@dataclass(frozen=True)
class ApplyResult:
    outcome: ApplyOutcome
    job: JobSnapshot
    reason: str | None = None


def change_status(
    job: JobSnapshot,
    target: JobStatusEnum,
    at: datetime,
    error_code: JobErrorCodeEnum | None = None,
    error_message: str | None = None,
) -> JobSnapshot:
    """Apply a status change decided by the API; raises InvalidStateTransitionError if it is not allowed."""
    validate_transition(job.status, target)

    changes: dict[str, Any] = {"status": target}
    if target == JobStatusEnum.PROCESSING and job.started_at is None:
        changes["started_at"] = at
    if final_state(target):
        changes["finished_at"] = at
    if error_code is not None:
        changes["error_code"] = error_code
    if error_message is not None:
        changes["error_message"] = error_message
    return replace(job, **changes)


def apply_event(job: JobSnapshot, event: JobUpdateEventSchema) -> ApplyResult:
    """Apply a worker event; duplicated, late or invalid events never change the job."""

    def ignored(reason: str) -> ApplyResult:
        return ApplyResult(ApplyOutcome.IGNORED, job, reason)

    def rejected(reason: str) -> ApplyResult:
        return ApplyResult(ApplyOutcome.REJECTED, job, reason)

    if event.status not in WORKER_REPORTABLE_STATUSES:
        return rejected(EVENT_REJECTED_STATUS.format(status=event.status.value))

    if event.step is not None:
        try:
            get_step_weight(job.job_type, event.step)
        except InvalidStepError as exc:
            return rejected(str(exc))

    if event.attempt < job.attempt:
        return ignored(EVENT_IGNORED_PAST_ATTEMPT)
    if event.attempt > job.attempt:
        return rejected(EVENT_REJECTED_UNKNOWN_ATTEMPT)

    if final_state(job.status):
        return ignored(EVENT_IGNORED_JOB_FINISHED.format(status=job.status.value))

    if job.last_event_at is not None and event.emitted_at < job.last_event_at:
        return ignored(EVENT_IGNORED_OUT_OF_ORDER)

    if event.status != job.status and not can_transition(job.status, event.status):
        return rejected(ERROR_INVALID_TRANSITION.format(current=job.status.value, target=event.status.value))

    changes: dict[str, Any] = {"status": event.status, "last_event_at": event.emitted_at}

    if event.status == JobStatusEnum.PROCESSING:
        step = event.step or job.step or JobStepProcessingEnum.INITIALIZING

        if job.step is not None:
            if get_step_weight(job.job_type, step)[0] < get_step_weight(job.job_type, job.step)[0]:
                return ignored(EVENT_IGNORED_EARLIER_STEP)
            if step == job.step and event.step_progress < job.step_progress:
                return ignored(EVENT_IGNORED_LOWER_PROGRESS)

        computed = calculate_progress(job.job_type, step, event.status, event.step_progress)
        changes["step"] = step
        changes["step_progress"] = event.step_progress
        changes["progress"] = max(job.progress, computed)
        if job.started_at is None:
            changes["started_at"] = event.emitted_at

    elif event.status == JobStatusEnum.COMPLETED:
        changes.update(
            step=JobStepProcessingEnum.FINISHED,
            step_progress=PROGRESS_MAX,
            progress=PROGRESS_MAX,
            output=event.output,
            finished_at=event.emitted_at,
        )

    else:
        if event.step is not None:
            changes["step"] = event.step
            changes["step_progress"] = event.step_progress

        changes["finished_at"] = event.emitted_at
        if event.status == JobStatusEnum.FAILED:
            changes.update(error_code=event.error_code, error_message=event.error_message)

    new_job = replace(job, **changes)
    if (new_job.status, new_job.step, new_job.step_progress, new_job.progress) == (
        job.status, job.step, job.step_progress, job.progress
    ):
        return ignored(EVENT_IGNORED_NO_CHANGE)

    return ApplyResult(ApplyOutcome.APPLIED, new_job)
