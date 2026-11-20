"""Private Google Slides OAuth credentials, separate from video production."""
from alembic import op
import sqlalchemy as sa
revision = 'd72e418bb023'
down_revision = 'b61d307aa912'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('google_slides_connections',
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('scopes', sa.Text(), nullable=False),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('google_slides_oauth_states',
        sa.Column('state_hash', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('verifier', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_google_slides_oauth_states_owner_id','google_slides_oauth_states',['owner_id'])
    for table in ('google_slides_connections','google_slides_oauth_states'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        for role in ('anon','authenticated'):
            op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON {table} FROM {role}; END IF; END $$")
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON {table} TO service_role; END IF; END $$")


def downgrade():
    raise RuntimeError('Preserve Google connection history; use a reviewed forward migration.')
