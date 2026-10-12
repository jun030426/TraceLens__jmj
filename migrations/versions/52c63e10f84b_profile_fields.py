"""Optional personal profile fields."""
from alembic import op
import sqlalchemy as sa
revision = "52c63e10f84b"
down_revision = "41b52d09e73a"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("major", sa.String(100)))
    op.add_column("users", sa.Column("student_number", sa.String(40)))
    op.add_column("users", sa.Column("avatar", sa.Text()))

def downgrade():
    for name in ("avatar", "student_number", "major"):
        op.drop_column("users", name)
