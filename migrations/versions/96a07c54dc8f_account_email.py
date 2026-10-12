"""Store account email; existing accounts may add it in their profile."""
from alembic import op
import sqlalchemy as sa
revision = "96a07c54dc8f"
down_revision = "85f96b43cb7e"
branch_labels = depends_on = None

def upgrade():
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))

def downgrade():
    op.drop_column("users", "email")
