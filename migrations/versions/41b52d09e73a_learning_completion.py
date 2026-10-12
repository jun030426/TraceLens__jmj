"""Persist completed learning independently of grading."""
from alembic import op
import sqlalchemy as sa
revision = "41b52d09e73a"
down_revision = "808bc4a721d4"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("learning_completions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("section_id", sa.String(36), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False))
    op.create_index("ix_learning_completions_student_id", "learning_completions", ["student_id"])
    op.create_index("uq_completion_source", "learning_completions", ["student_id", "domain", "source_id"], unique=True)
    op.execute("""INSERT INTO learning_completions
        (id, created_at, student_id, section_id, domain, source_id, day)
        SELECT s.id, max(a.created_at), s.student_id, s.section_id, 'theory', s.id,
               (max(a.created_at) AT TIME ZONE 'Asia/Seoul')::date
        FROM learning_sessions s JOIN attempts a ON a.learning_session_id = s.id
        WHERE json_array_length(s.question_ids) > 0
          AND a.question_id IN (SELECT json_array_elements_text(s.question_ids))
        GROUP BY s.id
        HAVING count(DISTINCT a.question_id) = json_array_length(s.question_ids)""")

def downgrade():
    op.drop_table("learning_completions")
