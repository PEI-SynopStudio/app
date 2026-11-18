"""initial schema

Revision ID: 0001
Revises: 
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('actor_hash', sa.String(length=64), nullable=True),
    sa.Column('action', sa.Enum('project.created', 'licence.confirmed', 'upload.started', 'ingestion.requested', 'ingestion.completed', 'ingestion.failed', 'project.deleted', name='auditaction', native_enum=False, length=64), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_created_at'), 'audit_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_log_project_id'), 'audit_log', ['project_id'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.String(length=255), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('author', sa.String(length=300), nullable=False),
    sa.Column('speakers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recording_date', sa.Date(), nullable=False),
    sa.Column('license_type', sa.Enum('creative_commons', 'institutional_permission', 'public_debate_rights', name='licensetype', native_enum=False, length=64), nullable=False),
    sa.Column('copyright_notice', sa.Text(), nullable=False),
    sa.Column('licence_confirmed', sa.Boolean(), nullable=False),
    sa.Column('authorship_confirmed', sa.Boolean(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'ingesting', 'ingested', 'ingestion_failed', name='projectstatus', native_enum=False, length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index(op.f('ix_projects_owner_id'), 'projects', ['owner_id'], unique=False)
    op.create_table('media_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('source_type', sa.Enum('upload', 'url', name='sourcetype', native_enum=False, length=64), nullable=False),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('status', sa.Enum('uploading', 'processing', 'ready', 'failed', name='mediaassetstatus', native_enum=False, length=64), nullable=False),
    sa.Column('time_start_seconds', sa.Double(), nullable=True),
    sa.Column('time_end_seconds', sa.Double(), nullable=True),
    sa.Column('container', sa.String(length=128), nullable=True),
    sa.Column('video_codec', sa.String(length=64), nullable=True),
    sa.Column('audio_codec', sa.String(length=64), nullable=True),
    sa.Column('duration_seconds', sa.Double(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('aspect_ratio', sa.String(length=32), nullable=True),
    sa.Column('frame_rate', sa.Double(), nullable=True),
    sa.Column('is_vfr', sa.Boolean(), nullable=True),
    sa.Column('sample_rate', sa.Integer(), nullable=True),
    sa.Column('channels', sa.Integer(), nullable=True),
    sa.Column('source_key', sa.String(length=1024), nullable=True),
    sa.Column('proxy_key', sa.String(length=1024), nullable=True),
    sa.Column('keyframes_key', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_media_assets_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets'))
    )
    op.create_index(op.f('ix_media_assets_project_id'), 'media_assets', ['project_id'], unique=False)
    op.create_table('audio_tracks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('media_asset_id', sa.Uuid(), nullable=False),
    sa.Column('sample_rate', sa.Integer(), nullable=False),
    sa.Column('channels', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('waveform_key', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], name=op.f('fk_audio_tracks_media_asset_id_media_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audio_tracks')),
    sa.UniqueConstraint('media_asset_id', name=op.f('uq_audio_tracks_media_asset_id'))
    )
    op.create_table('jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('media_asset_id', sa.Uuid(), nullable=True),
    sa.Column('job_type', sa.Enum('ingestion', 'transcription', name='jobtypeenum', native_enum=False, length=64), nullable=False),
    sa.Column('status', sa.Enum('pending', 'queued', 'processing', 'completed', 'failed', 'cancelled', name='jobstatusenum', native_enum=False, length=64), nullable=False),
    sa.Column('step', sa.Enum('initializing', 'downloading_media', 'inspecting_media', 'extracting_audio', 'generating_proxy', 'transcribing', 'diarizing', 'persisting_results', 'cleaning_up', 'finished', name='jobstepprocessingenum', native_enum=False, length=64), nullable=True),
    sa.Column('step_progress', sa.Double(), nullable=False),
    sa.Column('progress', sa.Double(), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.Enum('invalid_source', 'source_unavailable', 'duration_limit_exceeded', 'corrupted_media', 'no_audio_track', 'unsupported_format', 'silent_audio', 'internal_error', 'timeout', name='joberrorcodeenum', native_enum=False, length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], name=op.f('fk_jobs_media_asset_id_media_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_jobs_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_index(op.f('ix_jobs_media_asset_id'), 'jobs', ['media_asset_id'], unique=False)
    op.create_index(op.f('ix_jobs_project_id'), 'jobs', ['project_id'], unique=False)
    op.create_index('uq_jobs_one_active_ingestion_per_project', 'jobs', ['project_id'], unique=True, postgresql_where=sa.text("job_type = 'ingestion' AND status IN ('pending', 'queued', 'processing')"))
    op.create_table('upload_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('media_asset_id', sa.Uuid(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('chunk_size', sa.Integer(), nullable=False),
    sa.Column('total_chunks', sa.Integer(), nullable=False),
    sa.Column('staged_file', sa.String(length=255), nullable=False),
    sa.Column('assembled', sa.Boolean(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], name=op.f('fk_upload_sessions_media_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_upload_sessions_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_sessions')),
    sa.UniqueConstraint('media_asset_id', name=op.f('uq_upload_sessions_media_asset_id'))
    )
    op.create_index(op.f('ix_upload_sessions_project_id'), 'upload_sessions', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_upload_sessions_project_id'), table_name='upload_sessions')
    op.drop_table('upload_sessions')
    op.drop_index('uq_jobs_one_active_ingestion_per_project', table_name='jobs', postgresql_where=sa.text("job_type = 'ingestion' AND status IN ('pending', 'queued', 'processing')"))
    op.drop_index(op.f('ix_jobs_project_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_media_asset_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('audio_tracks')
    op.drop_index(op.f('ix_media_assets_project_id'), table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_index(op.f('ix_projects_owner_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_audit_log_project_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_created_at'), table_name='audit_log')
    op.drop_table('audit_log')
