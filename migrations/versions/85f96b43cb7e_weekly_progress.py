"""Section weekly schedules and actual progress."""
from alembic import op
import sqlalchemy as sa
revision = "85f96b43cb7e"
down_revision = "74e85a32ba6d"
branch_labels = depends_on = None
def upgrade():
    op.add_column("sections", sa.Column("week_schedule", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("sections", sa.Column("progress_week", sa.Integer(), nullable=True))
def downgrade():
    op.drop_column("sections", "progress_week")
    op.drop_column("sections", "week_schedule")
