import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import AuditAction
from app.database.models import AuditLog, User
from app.services.auth.auth import actor_hash


# Add one entry to the audit log; the caller commits it together with the change it records.
# Source: MS2 FR18 (audit trail); MS3 §1.4.3 (licence and editorial records kept for 12 months);
# MS3 §1.1.3 (the user is recorded as a SHA-256 of their ID, never by email).
def record_audit(
    db: Session,
    project_id: uuid.UUID,
    action: AuditAction,
    details: Optional[Dict[str, Any]] = None,
    actor: Optional[User] = None,
) -> AuditLog:
    """Without an actor the entry was made by the system (worker results, the periodic sweep)."""
    entry = AuditLog(
        project_id=project_id,
        action=action,
        details=details or {},
        actor_hash=actor_hash(actor.id) if actor else None,
    )
    db.add(entry)
    return entry
