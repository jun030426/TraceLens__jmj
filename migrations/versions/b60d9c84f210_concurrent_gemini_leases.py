"""Track independently expiring reservations per Gemini project and model."""
from alembic import op
import sqlalchemy as sa

revision = "b60d9c84f210"
down_revision = "af3e227a01db"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gemini_quotas", sa.Column("active_leases", sa.JSON(), nullable=True))

    op.create_table("gemini_paid_call_budgets",
                    sa.Column("version_id", sa.String(36), primary_key=True),
                    sa.Column("review", sa.Integer(), nullable=False),
                    sa.Column("embedding", sa.Integer(), nullable=False))
    op.execute("ALTER TABLE gemini_paid_call_budgets ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON gemini_paid_call_budgets FROM PUBLIC")
    for role in ("anon", "authenticated", "service_role"):
        action = "GRANT ALL ON gemini_paid_call_budgets TO" if role == "service_role" else "REVOKE ALL ON gemini_paid_call_budgets FROM"
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
                   f"THEN {action} {role}; END IF; END $$")


def downgrade():
    op.drop_table("gemini_paid_call_budgets")
    op.drop_column("gemini_quotas", "active_leases")
