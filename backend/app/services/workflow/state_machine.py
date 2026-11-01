from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any

from app.schemas.enums import JobStatusEnum, JobStepProcessingEnum, JobTypeEnum, JobErrorCodeEnum
from app.core.exceptions import InvalidStepError  

from app.schemas.job import JobUpdateEventSchema
from app.services.workflow.progress import calculateprogress, getstepweight
from app.services.workflow.transitions import final_state, can_transition, validate_transition

WORKER_STATUS = (
    JobStatusEnum.PROCESSING,
    JobStatusEnum.COMPLETED,
    JobStatusEnum.FAILED,
    JobStatusEnum.CANCELLED,
)

# estado de uma tarefa
@dataclass(frozen=True)
class JobSnapshot:
    job_type: JobTypeEnum
    status: JobStatusEnum = JobStatusEnum.PENDING
    step: JobStepProcessingEnum | None = None
    step_progress: float = 0.0
    progress: float = 0.0
    attempt: int = 1
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_event_at: datetime | None = None
    

# resultado de uma operação
class ApplyOutcome(str, Enum):
    APPLIED = "applied" # mudou
    IGNORED = "ignored" # sem efeito
    REJECTED = "rejected" # inválido

@dataclass(frozen=True)
class ApplyResult:
    outcome: ApplyOutcome
    job: JobSnapshot
    reason: str | None = None
    
def change_status(job: JobSnapshot, target: JobStatusEnum, at: datetime) -> JobSnapshot:
    validate_transition(job.status, target)
    
    changes: dict[str, Any] = {"status":target}
    if target == JobStatusEnum.PROCESSING and job.started_at is None:
        changes["started_at"] = at
    if final_state(target):
        changes["finished_at"] = at
    return replace(job, **changes) # transforma as chaves e valores em argumentos




def apply_event(job: JobSnapshot, event: JobUpdateEventSchema) -> ApplyResult:
    def ignored(reason: str) -> ApplyResult:
        return ApplyResult(ApplyOutcome.IGNORED, job, reason)

    def rejected(reason: str) -> ApplyResult:
        return ApplyResult(ApplyOutcome.REJECTED, job, reason)
    
    if event.status not in WORKER_STATUS:
        return rejected(f"Don't report this stat {event.status.value}")
    
    if event.step is not None:
        try:
            getstepweight(job.job_type, event.step)
        except InvalidStepError:
            return rejected(str(InvalidStepError))
        
    if event.attempt < job.attempt:
        return ignored("Past event attempt")
    if event.attempt > job.attempt:
        return rejected("Event attempt unknown")
    
    if final_state(job.status):
        return ignored(f"Job Finished ({job.status.value})")
    
    if job.last_event_at is not None and event.emitted_at < job.last_event_at:
        return ignored("An event that occurred earlier than the most recent one")
    
    if event.status != job.status and not can_transition(job.status, event.status):
        return rejected(f"Imvalid transiction")
    
    changes: dict[str, Any] = {"status": event.status, "last_event_at": event.emitted_at}
    
    if event.status == JobStatusEnum.PROCESSING:
        step = event.step or job.step or JobStepProcessingEnum.INITIALIZING
        
        if job.step is not None:
            if getstepweight(job.job_type, step)[0] < getstepweight(job.job_type, job.step)[0]:
                return ignored("Step preceding the current one")
            
            if step == job.step and event.step_progress < job.step_progress:
                return ignored("Progress at a slower pace than the current one")
            
            
        computed = calculateprogress(job.job_type, step, event.status, event.step_progress)
        changes["step"] = step
        changes["step_progress"] = event.step_progress
        changes["progress"] = max(job.progress, computed)
        if job.started_at is None:
            changes["started_at"] = event.emitted_at
            
    elif event.status == JobStatusEnum.COMPLETED:
        changes.update(step=JobStepProcessingEnum.FINISHED, step_progress=100.0, progress=100.0, output=event.output, finished_at=event.emitted_at)
        
    else:
        if event.step is not None:
            changes["step"] == event.step
        
        changes["finished_at"] = event.emitted_at
        if event.status == JobStatusEnum.FAILED:
            changes.update(error_code=event.error_code, error_message=event.error_message)
            
    new_job = replace(job, **changes)
    if (new_job.status, new_job.step, new_job.step_progress, new_job.progress) == (job.status, job.step, job.step_progress, job.progress):
        return ignored("Without changes")
    
    return ApplyResult(ApplyOutcome.APPLIED, new_job)
            
            