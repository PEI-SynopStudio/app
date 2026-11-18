from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('transcripts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('media_asset_id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('model_name', sa.String(length=255), nullable=False),
    sa.Column('model_revision', sa.String(length=64), nullable=False),
    sa.Column('alignment_model_name', sa.String(length=255), nullable=False),
    sa.Column('alignment_model_revision', sa.String(length=64), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('time_offset_seconds', sa.Double(), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('ai_generated', sa.Boolean(), nullable=False),
    sa.Column('segment_count', sa.Integer(), nullable=False),
    sa.Column('word_count', sa.Integer(), nullable=False),
    sa.Column('aligned_word_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_transcripts_job_id_jobs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], name=op.f('fk_transcripts_media_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_transcripts_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcripts')),
    sa.UniqueConstraint('media_asset_id', name=op.f('uq_transcripts_media_asset_id'))
    )
    op.create_index(op.f('ix_transcripts_project_id'), 'transcripts', ['project_id'], unique=False)
    op.create_table('transcript_segments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('transcript_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('start_seconds', sa.Double(), nullable=False),
    sa.Column('end_seconds', sa.Double(), nullable=False),
    sa.Column('confidence', sa.Double(), nullable=False),
    sa.Column('avg_logprob', sa.Double(), nullable=False),
    sa.Column('no_speech_prob', sa.Double(), nullable=False),
    sa.Column('compression_ratio', sa.Double(), nullable=False),
    sa.Column('temperature', sa.Double(), nullable=False),
    sa.ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], name=op.f('fk_transcript_segments_transcript_id_transcripts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcript_segments')),
    sa.UniqueConstraint('transcript_id', 'position', name=op.f('uq_transcript_segments_transcript_id'))
    )
    op.create_index('ix_transcript_segments_transcript_id_start_seconds', 'transcript_segments', ['transcript_id', 'start_seconds'], unique=False)
    op.create_table('transcript_words',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('transcript_id', sa.Uuid(), nullable=False),
    sa.Column('segment_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('start_seconds', sa.Double(), nullable=False),
    sa.Column('end_seconds', sa.Double(), nullable=False),
    sa.Column('confidence', sa.Double(), nullable=False),
    sa.Column('aligned', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['segment_id'], ['transcript_segments.id'], name=op.f('fk_transcript_words_segment_id_transcript_segments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], name=op.f('fk_transcript_words_transcript_id_transcripts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcript_words')),
    sa.UniqueConstraint('transcript_id', 'position', name=op.f('uq_transcript_words_transcript_id'))
    )
    op.create_index(op.f('ix_transcript_words_segment_id'), 'transcript_words', ['segment_id'], unique=False)
    op.create_index('ix_transcript_words_transcript_id_start_seconds', 'transcript_words', ['transcript_id', 'start_seconds'], unique=False)
    op.create_index('uq_jobs_one_active_transcription_per_project', 'jobs', ['project_id'], unique=True, postgresql_where=sa.text("job_type = 'transcription' AND status IN ('pending', 'queued', 'processing')"))


def downgrade() -> None:
    op.drop_index('uq_jobs_one_active_transcription_per_project', table_name='jobs', postgresql_where=sa.text("job_type = 'transcription' AND status IN ('pending', 'queued', 'processing')"))
    op.drop_index('ix_transcript_words_transcript_id_start_seconds', table_name='transcript_words')
    op.drop_index(op.f('ix_transcript_words_segment_id'), table_name='transcript_words')
    op.drop_table('transcript_words')
    op.drop_index('ix_transcript_segments_transcript_id_start_seconds', table_name='transcript_segments')
    op.drop_table('transcript_segments')
    op.drop_index(op.f('ix_transcripts_project_id'), table_name='transcripts')
    op.drop_table('transcripts')
