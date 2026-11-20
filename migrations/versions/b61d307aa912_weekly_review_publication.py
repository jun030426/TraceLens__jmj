"""Instructor-triggered weekly content with explicit review/publication.

Revision ID: b61d307aa912
Revises: 8f2a7c19d601
"""
from alembic import op
import sqlalchemy as sa

revision = 'b61d307aa912'
down_revision = '8f2a7c19d601'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('daily_plans','job_id',existing_type=sa.String(36),nullable=True)
    op.create_table('content_generations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('course_id', sa.String(36), sa.ForeignKey('courses.id'), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('concept_ids', sa.JSON(), nullable=False),
        sa.Column('concept_evidence', sa.JSON(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('published_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint('week BETWEEN 1 AND 52', name='ck_content_week'))
    op.create_index('ix_content_generations_course_id','content_generations',['course_id'])
    for state in ('draft','published'):
        op.create_index('uq_week_content_'+state,'content_generations',['course_id','week'],unique=True,
                        postgresql_where=sa.text("status = '"+state+"'"))
    for table in ('questions','concept_videos','practice_exercises'):
        op.add_column(table,sa.Column('generation_id',sa.String(36),sa.ForeignKey('content_generations.id')))
        op.create_index('ix_'+table+'_generation_id',table,['generation_id'])
    op.drop_index('uq_video_source_concept',table_name='concept_videos')
    op.create_index('uq_video_generation_concept','concept_videos',['generation_id','concept_id'],unique=True)
    op.drop_index('uq_exercise_source_key',table_name='practice_exercises')
    op.create_index('uq_exercise_generation_key','practice_exercises',['generation_id','source_key','kind'],unique=True)
    op.execute('ALTER TABLE content_generations ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON content_generations FROM PUBLIC')
    for role in ('anon','authenticated'):
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON content_generations FROM {role}; END IF; END $$")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON content_generations TO service_role; END IF; END $$")
    # Retain generated artifacts/history, but stop pre-review automatic work.
    op.execute("""UPDATE jobs SET status='cancelled',error_code='MANUAL_GENERATION_REQUIRED',
        lease_token=NULL,lease_until=NULL WHERE kind IN ('auto_concepts','questions','narration_lesson','practice_prepare','daily_theory')
        AND status IN ('queued','running','waiting_ai') AND payload->>'generation_id' IS NULL""")
    op.execute("""UPDATE concept_videos SET status='held',error_code='MANUAL_GENERATION_REQUIRED'
        WHERE generation_id IS NULL AND provider_session_id IS NULL AND status IN ('script_pending','queued')""")
    # A teacher publication will populate automatic progress from reviewed generations.
    op.execute("UPDATE sections SET progress='[]'::json,revision=revision+1 WHERE progress_mode='auto'")


def downgrade():
    raise RuntimeError('Weekly publication history requires a reviewed forward migration; do not discard it.')
