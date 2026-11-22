"""Keep the original archive slot when a current-week assignment replaces it."""
from alembic import op
import sqlalchemy as sa

revision = "af3e227a01db"
down_revision = "f18ab47c9821"
branch_labels = depends_on = None


def upgrade():
    op.add_column("learning_sessions", sa.Column("archive_week", sa.Integer()))
    op.add_column("learning_sessions", sa.Column("archive_day_index", sa.Integer()))
    op.drop_index("uq_daily_student_section", table_name="learning_sessions")
    op.create_index("uq_daily_student_section", "learning_sessions", ["student_id", "section_id", "day"],
                    unique=True, postgresql_where=sa.text("archive_week IS NULL"))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT FROM learning_sessions WHERE archive_week IS NOT NULL)")):
        raise RuntimeError("Preserve assigned archive slots before downgrading.")
    op.drop_index("uq_daily_student_section", table_name="learning_sessions")
    op.create_index("uq_daily_student_section", "learning_sessions", ["student_id", "section_id", "day"], unique=True)
    op.drop_column("learning_sessions", "archive_day_index")
    op.drop_column("learning_sessions", "archive_week")
