import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import String, Uuid, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import ACTOR_HASH_MAX_LENGTH, ERROR_AUDIT_LOG_IMMUTABLE, TABLE_AUDIT_LOG, AuditAction
from app.database.base import Base, enum_type, utc_now


class AuditLog(Base):
    """Append-only record of licence and editorial decisions (FR18, MS3 §1.4.3).

    project_id has no foreign key on purpose: these records outlive the project for 12 months.
    """

    __tablename__ = TABLE_AUDIT_LOG

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    # Hash of the user ID, never the email (MS3 §1.1.3); empty until authentication exists.
    actor_hash: Mapped[Optional[str]] = mapped_column(String(ACTOR_HASH_MAX_LENGTH))
    action: Mapped[AuditAction] = mapped_column(enum_type(AuditAction))
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)


def _refuse_change(mapper, connection, target) -> None:
    raise RuntimeError(ERROR_AUDIT_LOG_IMMUTABLE)


event.listen(AuditLog, "before_update", _refuse_change)
event.listen(AuditLog, "before_delete", _refuse_change)
