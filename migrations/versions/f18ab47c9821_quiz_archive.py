"""Weekly practice assignments and separately graded theory retakes."""
from alembic import op
import sqlalchemy as sa

revision = "f18ab47c9821"
down_revision = "e83f529cc134"
branch_labels = depends_on = None


def upgrade():
    op.alter_column("practice_sessions", "day", existing_type=sa.Date(), nullable=True)
    op.create_index("uq_weekly_practice_archive", "practice_sessions",
                    ["student_id", "section_id", "week"], unique=True,
                    postgresql_where=sa.text("day IS NULL"))
    op.create_table("theory_retakes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_id", sa.String(36), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer()), sa.Column("correct", sa.Boolean()),
        sa.Column("feedback", sa.JSON()))
    op.create_index("ix_theory_retakes_original_id", "theory_retakes", ["original_id"])
    op.execute("ALTER TABLE theory_retakes ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON theory_retakes FROM PUBLIC")
    for role in ("anon", "authenticated"):
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON theory_retakes FROM {role}; END IF; END $$")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON theory_retakes TO service_role; END IF; END $$")


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS (SELECT FROM theory_retakes) OR EXISTS (SELECT FROM practice_sessions WHERE day IS NULL)")):
        raise RuntimeError("Preserve existing quiz archive records before downgrading.")
    op.drop_table("theory_retakes")
    op.drop_index("uq_weekly_practice_archive", table_name="practice_sessions")
    op.alter_column("practice_sessions", "day", existing_type=sa.Date(), nullable=False)
