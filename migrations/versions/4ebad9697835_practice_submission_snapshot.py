"""Store the template information shown at the time of a practice submission."""

from alembic import op
import sqlalchemy as sa

revision = "4ebad9697835"
down_revision = "b60d9c84f210"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("practice_attempts", sa.Column("submission_snapshot", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("practice_attempts", "submission_snapshot")
