"""Keycloak owns passwords, lockout and account status: drop them and require the Keycloak link

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Accounts from before Keycloak cannot sign in any more; their sessions go with them (ON DELETE CASCADE).
    op.execute("DELETE FROM users WHERE subject IS NULL")
    # A session without its sign-in time could never pass the re-authentication check.
    op.execute("DELETE FROM auth_sessions WHERE authenticated_at IS NULL")
    op.alter_column('users', 'subject', existing_type=sa.String(length=255), nullable=False)
    op.alter_column('auth_sessions', 'authenticated_at', existing_type=sa.DateTime(timezone=True), nullable=False)
    # Keycloak keeps emails unique; a copy here must not block a sign-in after an email moves between accounts.
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'failed_login_count')
    op.drop_column('users', 'locked_until')


def downgrade() -> None:
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    # Server defaults only fill the existing rows; the old schema had none.
    op.add_column('users', sa.Column('failed_login_count', sa.Integer(), server_default='0', nullable=False))
    op.alter_column('users', 'failed_login_count', server_default=None)
    op.add_column('users', sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column('users', 'is_active', server_default=None)
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.alter_column('auth_sessions', 'authenticated_at', existing_type=sa.DateTime(timezone=True), nullable=True)
    op.alter_column('users', 'subject', existing_type=sa.String(length=255), nullable=True)
