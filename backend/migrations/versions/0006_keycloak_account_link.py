"""link accounts and sessions to Keycloak

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('subject', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_users_subject'), 'users', ['subject'], unique=True)
    op.add_column('auth_sessions', sa.Column('idp_session_id', sa.String(length=255), nullable=True))
    op.add_column('auth_sessions', sa.Column('authenticated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('auth_sessions', 'authenticated_at')
    op.drop_column('auth_sessions', 'idp_session_id')
    op.drop_index(op.f('ix_users_subject'), table_name='users')
    op.drop_column('users', 'subject')