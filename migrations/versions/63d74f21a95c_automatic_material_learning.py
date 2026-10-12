"""Automatic material learning."""
from alembic import op
import sqlalchemy as sa
revision = "63d74f21a95c"
down_revision = "52c63e10f84b"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("sections", sa.Column("progress_mode",sa.String(10),nullable=False,server_default="auto"))
    op.execute("UPDATE sections SET progress_mode='manual' WHERE json_array_length(progress)>0")
    op.add_column("material_versions",sa.Column("concept_ids",sa.JSON(),nullable=False,server_default="[]"))
def downgrade():
    op.drop_column("material_versions","concept_ids")
    op.drop_column("sections","progress_mode")
