"""One operator-managed Google Slides connection; preserve previous connection history."""
from alembic import op
import sqlalchemy as sa

revision = 'e83f529cc134'
down_revision = 'd72e418bb023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('google_slides_service_connections',
        sa.Column('id', sa.String(30), primary_key=True),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('scopes', sa.Text(), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False))
    op.alter_column('google_slides_oauth_states', 'owner_id', existing_type=sa.String(36), nullable=True)
    table = 'google_slides_service_connections'
    op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
    op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
    for role in ('anon', 'authenticated'):
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON {table} FROM {role}; END IF; END $$")
    op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON {table} TO service_role; END IF; END $$")


def downgrade():
    raise RuntimeError('Preserve Google connection history; use a reviewed forward migration.')
