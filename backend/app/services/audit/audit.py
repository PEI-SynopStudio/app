import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import AuditAction
from app.database.models import AuditLog


# Add one entry to the audit log; the caller commits it together with the change it records.
# Source: MS2 FR18 (audit trail); MS3 §1.4.3 (licence and editorial records kept for 12 months).
def record_audit(
    db: Session, project_id: uuid.UUID, action: AuditAction, details: Optional[Dict[str, Any]] = None
) -> AuditLog:
    entry = AuditLog(project_id=project_id, action=action, details=details or {})
    db.add(entry)
    return entry
