"""store the object storage ID of each upload

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The chunks of the uploads in progress are on the local volume and cannot be resumed;
    # deleting their media assets also deletes their sessions (cascade).
    op.execute('DELETE FROM media_assets WHERE id IN (SELECT media_asset_id FROM upload_sessions)')
    op.add_column('upload_sessions', sa.Column('storage_upload_id', sa.String(length=1024), nullable=False))


def downgrade() -> None:
    op.drop_column('upload_sessions', 'storage_upload_id')
