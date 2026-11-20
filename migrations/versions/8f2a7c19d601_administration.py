"""Server-only administrator MFA, operations gates, and durable EC2 commands."""
from alembic import op
import sqlalchemy as sa

revision = "8f2a7c19d601"
down_revision = "5ad317c8be12"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("admin_grants",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("mfa_secret", sa.Text()), sa.Column("pending_secret", sa.Text()),
        sa.Column("pending_until", sa.DateTime(timezone=True)),
        sa.Column("last_counter", sa.Integer(), nullable=False),
        sa.Column("recovery_hashes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("admin_proofs",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("login_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("operations_state",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("maintenance", sa.Boolean(), nullable=False), sa.Column("message", sa.String(500), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False), sa.Column("server_hold", sa.Boolean(), nullable=False),
        sa.Column("scheduler_seen_at", sa.DateTime(timezone=True)))
    op.execute(sa.text("INSERT INTO operations_state (id, revision, maintenance, message, features, server_hold) "
        "VALUES (1, 1, false, '현재 서비스 점검 중입니다. 잠시 후 다시 이용해 주세요.', '{}', false)"))
    op.create_table("operations_workers",
        sa.Column("id", sa.String(100), primary_key=True), sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("server_id", sa.String(30)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False), sa.Column("busy", sa.Boolean(), nullable=False))
    op.create_table("server_commands",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False), sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("error_code", sa.String(80)),
        sa.Column("request_id", sa.String(100)), sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_server_commands_status", "server_commands", ["status"])
    for table in ("admin_grants", "admin_proofs", "operations_state", "operations_workers", "server_commands"):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        for role in ("anon", "authenticated"):
            op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON {table} FROM {role}; END IF; END $$")
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN GRANT ALL ON {table} TO service_role; END IF; END $$")


def downgrade():
    for table in ("server_commands", "operations_workers", "operations_state", "admin_proofs", "admin_grants"):
        op.drop_table(table)
