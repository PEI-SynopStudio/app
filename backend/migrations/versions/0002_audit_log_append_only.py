"""make the audit log append-only

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FR18: entries are immutable. MS3 §1.4.3: they may only be removed after the 12-month retention period.
    op.execute("""
        CREATE FUNCTION audit_log_protect() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.created_at < now() - interval '12 months' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Audit log entries cannot be changed or deleted.';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_log_protect BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_protect()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_protect ON audit_log")
    op.execute("DROP FUNCTION audit_log_protect()")
