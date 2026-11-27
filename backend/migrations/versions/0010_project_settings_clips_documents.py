"""project settings, clips and supporting documents

Revision ID: 0010
Revises: 0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _aspect_ratio() -> sa.Enum:
    return sa.Enum('9:16', '1:1', '4:5', '16:9', name='aspectratio', native_enum=False, length=64)


def _language() -> sa.Enum:
    return sa.Enum('pt-PT', 'en', 'es', name='language', native_enum=False, length=64)


def _caption_style() -> sa.Enum:
    return sa.Enum('classic', 'bold', 'boxed', 'minimal', name='captionstyle', native_enum=False, length=64)


def upgrade() -> None:
    # The server defaults only fill the projects that already exist (the defaults of the New Project form);
    # they are dropped right after, because new rows get their values from the model.
    op.add_column('projects', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('aspect_ratio', _aspect_ratio(), nullable=False, server_default='9:16'))
    op.add_column('projects', sa.Column('language', _language(), nullable=False, server_default='pt-PT'))
    op.add_column('projects', sa.Column('caption_style', _caption_style(), nullable=True, server_default='classic'))
    for column in ('aspect_ratio', 'language', 'caption_style'):
        op.alter_column('projects', column, server_default=None)

    op.create_table('clips',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('scenes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subtitle_language', _language(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_clips_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clips'))
    )
    op.create_index(op.f('ix_clips_project_id'), 'clips', ['project_id'], unique=False)

    op.create_table('project_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=16), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_documents_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_documents'))
    )
    op.create_index(op.f('ix_project_documents_project_id'), 'project_documents', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_project_documents_project_id'), table_name='project_documents')
    op.drop_table('project_documents')
    op.drop_index(op.f('ix_clips_project_id'), table_name='clips')
    op.drop_table('clips')
    op.drop_column('projects', 'caption_style')
    op.drop_column('projects', 'language')
    op.drop_column('projects', 'aspect_ratio')
    op.drop_column('projects', 'description')