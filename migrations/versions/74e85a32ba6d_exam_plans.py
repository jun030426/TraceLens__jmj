"""Optional exam preparation."""
from alembic import op
import sqlalchemy as sa
revision="74e85a32ba6d"
down_revision="63d74f21a95c"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("exam_plans",sa.Column("id",sa.String(36),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("course_id",sa.String(36),sa.ForeignKey("courses.id"),nullable=False),sa.Column("title",sa.String(100),nullable=False),sa.Column("start_week",sa.Integer(),nullable=False),sa.Column("end_week",sa.Integer(),nullable=False),sa.Column("published",sa.Boolean(),nullable=False),sa.Column("revision",sa.Integer(),nullable=False))
    op.create_index("ix_exam_plans_course_id","exam_plans",["course_id"])
def downgrade():
    op.drop_table("exam_plans")
