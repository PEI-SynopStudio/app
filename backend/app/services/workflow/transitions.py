from __future__ import annotations

from app.schemas.enums import JobStatusEnum
from app.core.exceptions import InvalidStateTransitionError



def final_state(status: JobStatusEnum) -> bool:
    if (status == JobStatusEnum.CANCELLED or status == JobStatusEnum.FAILED or status == JobStatusEnum.COMPLETED):
        return True
    else:
        return False


def can_transition(current: JobStatusEnum, target: JobStatusEnum) -> bool:
    match (current, target):
        case (JobStatusEnum.PENDING, JobStatusEnum.QUEUED | JobStatusEnum.CANCELLED | JobStatusEnum.FAILED):
            return True
        case (JobStatusEnum.QUEUED, JobStatusEnum.PROCESSING | JobStatusEnum.CANCELLED | JobStatusEnum.FAILED):
            return True
        case (JobStatusEnum.PROCESSING, JobStatusEnum.FAILED | JobStatusEnum.COMPLETED | JobStatusEnum.CANCELLED):
            return True
        case _:
            return False
        
        
def validate_transition(current: JobStatusEnum, target: JobStatusEnum) -> None:
    if not can_transition(current, target):
        raise InvalidStateTransitionError(getattr(current, "value", str(current)), getattr(target, "value", str(target)))