from __future__ import annotations

from app.core.config import (
    ERROR_CODE_APP,
    ERROR_CODE_INVALID_STEP,
    ERROR_CODE_INVALID_TRANSITION,
    ERROR_CODE_JOB_NOT_FOUND,
    ERROR_CODE_JOB_TERMINAL,
    ERROR_CODE_STALE_ATTEMPT,
    ERROR_INVALID_STEP,
    ERROR_INVALID_TRANSITION,
    ERROR_JOB_ALREADY_TERMINAL,
    ERROR_JOB_NOT_FOUND,
    ERROR_STALE_JOB_ATTEMPT,
)


class AppError(Exception):
    """Base domain exception of the backend."""

    def __init__(self, message: str, code: str = ERROR_CODE_APP) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    """Resource not found (HTTP 404)."""


class ConflictError(AppError):
    """Conflict with the current state of the resource (HTTP 409)."""


class DomainValidationError(AppError):
    """Business rule or validation failure (HTTP 422)."""


class JobNotFoundError(NotFoundError):
    def __init__(self, message: str = ERROR_JOB_NOT_FOUND) -> None:
        super().__init__(message=message, code=ERROR_CODE_JOB_NOT_FOUND)


class InvalidStateTransitionError(ConflictError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            message=ERROR_INVALID_TRANSITION.format(current=current, target=target),
            code=ERROR_CODE_INVALID_TRANSITION,
        )


class JobAlreadyTerminalError(ConflictError):
    def __init__(self, status: str) -> None:
        super().__init__(message=ERROR_JOB_ALREADY_TERMINAL.format(status=status), code=ERROR_CODE_JOB_TERMINAL)


class StaleJobAttemptError(ConflictError):
    def __init__(self, event_attempt: int, current_attempt: int) -> None:
        super().__init__(
            message=ERROR_STALE_JOB_ATTEMPT.format(event_attempt=event_attempt, current_attempt=current_attempt),
            code=ERROR_CODE_STALE_ATTEMPT,
        )


class InvalidStepError(DomainValidationError):
    def __init__(self, job_type: str, step: str) -> None:
        self.job_type = job_type
        self.step = step
        super().__init__(message=ERROR_INVALID_STEP.format(step=step, job_type=job_type), code=ERROR_CODE_INVALID_STEP)
