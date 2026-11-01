from __future__ import annotations

class AppError(Exception):
    """Exceção base de domínio para todo o backend SynopStudio."""

    def __init__(self, message: str, code: str = "app_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)
      
   
class NotFoundError(AppError):
    """Recurso não encontrado (mapeia para HTTP 404)."""
   
class ConflictError(AppError):
    """Conflito de estado atual do recurso (mapeia para HTTP 409)."""  
    
class DomainValidationError(AppError):
    """Regra de negócio ou validação violada (mapeia para HTTP 422 / 400)."""
        
    
class JobNotFoundError(NotFoundError):
    def __init__(self, message: str = "Job not found") -> None:
        super().__init__(message=message, code="job_not_found")    
    
class InvalidStateTransitionError(ConflictError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(message=f"Invalid Transition: {current} -> {target}", code="invalid_state_transition")
        
class JobAlreadyTerminalError(ConflictError):
    def __init__(self, status: str) -> None:
        super().__init__(
            message=f"Worker already on terminal status ({status})",
            code="job_already_terminal",
        )

class StaleJobAttemptError(ConflictError):
    def __init__(self, event_attempt: int, current_attempt: int) -> None:
        super().__init__(
            message=f"Past attempt event ignored ({event_attempt} < {current_attempt}).",
            code="stale_job_attempt",
        )


class InvalidStepError(DomainValidationError):
    def __init__(self, job_type: str, step: str) -> None:
        self.job_type = job_type
        self.step = step
        super().__init__(
            message=f"Step '{step}' doesn't belong to pipeline '{job_type}'",
            code="invalid_step",
        )
        
