from __future__ import annotations

from app.core.config import (
    JOB_RUNNING_PROGRESS_CAP,
    JOB_STEP_WEIGHTS,
    PROGRESS_DECIMALS,
    PROGRESS_MAX,
    PROGRESS_MIN,
)
from app.core.exceptions import InvalidStepError
from app.schemas.enums import JobStatusEnum, JobStepProcessingEnum, JobTypeEnum


def get_step_weight(job_type: JobTypeEnum, step: JobStepProcessingEnum) -> tuple[float, float]:
    """Return the (start, end) share of the total progress covered by a step of the pipeline."""
    try:
        return JOB_STEP_WEIGHTS[job_type][step]
    except KeyError:
        raise InvalidStepError(job_type.value, step.value) from None


def calculate_progress(
    job_type: JobTypeEnum, step: JobStepProcessingEnum | None, status: JobStatusEnum, step_progress: float
) -> float:
    """Convert the progress inside a step into the job's total progress."""
    if status == JobStatusEnum.COMPLETED:
        return PROGRESS_MAX
    if step is None:
        return PROGRESS_MIN

    start, end = get_step_weight(job_type, step)
    clamped = max(PROGRESS_MIN, min(PROGRESS_MAX, step_progress))
    progress = start + (clamped / PROGRESS_MAX) * (end - start)
    return min(round(progress, PROGRESS_DECIMALS), JOB_RUNNING_PROGRESS_CAP)
