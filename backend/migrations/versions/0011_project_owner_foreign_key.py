"""projects reference the account that owns them

Revision ID: 0011
Revises: 0010
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # An owner_id that names no account is cleared: the accounts from before Keycloak (removed by 0008) left
    # their projects behind. No one could reach those projects anyway, and the foreign key would refuse them.
    op.execute(
        "UPDATE projects SET owner_id = NULL "
        "WHERE owner_id IS NOT NULL AND owner_id NOT IN (SELECT id::text FROM users)"
    )
    op.alter_column(
        'projects',
        'owner_id',
        existing_type=sa.String(length=255),
        type_=sa.Uuid(),
        existing_nullable=True,
        postgresql_using='owner_id::uuid',
    )
    op.create_foreign_key(
        op.f('fk_projects_owner_id_users'), 'projects', 'users', ['owner_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_projects_owner_id_users'), 'projects', type_='foreignkey')
    op.alter_column(
        'projects',
        'owner_id',
        existing_type=sa.Uuid(),
        type_=sa.String(length=255),
        existing_nullable=True,
        postgresql_using='owner_id::text',
    )