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
        
        
class InvalidStateTransitionError(ConflictError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(message=f"Invalid Transition: {current} -> {target}", code="invalid_state_transition")