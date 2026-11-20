"""shared code execution queue

Revision ID: 0cefe6893fc3
Revises: a7b18d65ec90
"""
from alembic import op
import sqlalchemy as sa


revision = '0cefe6893fc3'
down_revision = 'a7b18d65ec90'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('material_versions', sa.Column('extraction_report', sa.JSON(), nullable=True))
    op.create_table('code_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('section_id', sa.String(36), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('language', sa.String(10), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(40), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_token', sa.String(36), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    )
    for column in ('owner_id', 'section_id', 'status', 'expires_at'):
        op.create_index('ix_code_runs_' + column, 'code_runs', [column])
    op.create_table('code_workers',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ready', sa.Boolean(), nullable=False),
    )
    for table in ('code_runs', 'code_workers'):
        op.execute(sa.text('ALTER TABLE ' + table + ' ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text('REVOKE ALL ON ' + table + ' FROM PUBLIC'))
        # Supabase browser roles do not exist on isolated local PostgreSQL installs.
        for role in ('anon', 'authenticated'):
            op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='" + role + "') THEN REVOKE ALL ON " + table + " FROM " + role + "; END IF; END $$"))
        op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON " + table + " TO service_role; END IF; END $$"))

def downgrade():
    op.drop_table('code_workers')
    op.drop_table('code_runs')
    op.drop_column('material_versions', 'extraction_report')
