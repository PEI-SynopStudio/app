"""accounts created through Keycloak have no password

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # The old schema requires a password; accounts without one cannot be kept (their sessions go by cascade).
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)