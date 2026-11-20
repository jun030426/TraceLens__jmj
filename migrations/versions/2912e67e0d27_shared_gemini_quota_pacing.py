"""shared Gemini quota pacing

Revision ID: 2912e67e0d27
Revises: c4a7d92e1160
"""
from alembic import op
import sqlalchemy as sa


revision = '2912e67e0d27'
down_revision = 'c4a7d92e1160'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('gemini_quotas',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('next_at', sa.Float(), nullable=False),
        sa.Column('active_until', sa.Float(), nullable=False),
        sa.Column('active_token', sa.String(36)),
        sa.Column('blocked_until', sa.Float(), nullable=False),
        sa.Column('blocked_code', sa.String(50)),
        sa.Column('recent', sa.JSON(), nullable=False),
        sa.Column('day', sa.String(10), nullable=False),
        sa.Column('day_count', sa.Integer(), nullable=False))
    op.execute('ALTER TABLE gemini_quotas ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON gemini_quotas FROM PUBLIC')
    for role in ('anon', 'authenticated'):
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON gemini_quotas FROM {role}; END IF; END $$")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON gemini_quotas TO service_role; END IF; END $$")

def downgrade():
    op.drop_table('gemini_quotas')
