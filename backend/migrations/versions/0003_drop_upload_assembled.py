"""drop the assembled flag of upload sessions

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('upload_sessions', 'assembled')


def downgrade() -> None:
    op.add_column(
        'upload_sessions', sa.Column('assembled', sa.Boolean(), nullable=False, server_default=sa.false())
    )
