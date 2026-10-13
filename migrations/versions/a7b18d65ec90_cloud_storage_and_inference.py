"""Durable model requests, upload intents, and server-only application tables."""

import sqlalchemy as sa
from alembic import op

revision = "a7b18d65ec90"
down_revision = "96a07c54dc8f"
branch_labels = depends_on = None

APP_TABLES = [
    "users",
    "login_sessions",
    "login_attempts",
    "reset_tokens",
    "terms",
    "courses",
    "course_staff",
    "sections",
    "enrollments",
    "audit_events",
    "materials",
    "material_versions",
    "chunks",
    "concepts",
    "jobs",
    "chat_messages",
    "idempotency_records",
    "questions",
    "learning_sessions",
    "attempts",
    "reviews",
    "learning_completions",
    "exam_plans",
    "model_calls",
    "ai_workers",
    "upload_intents",
]


def identity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "model_calls",
        *identity(),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(50)),
    )
    op.create_index(
        "uq_model_call", "model_calls", ["job_id", "generation", "fingerprint"], unique=True
    )
    op.create_index("ix_model_calls_job_id", "model_calls", ["job_id"])
    op.create_index("ix_model_calls_status", "model_calls", ["status"])
    op.create_table(
        "ai_workers",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("models_ready", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "upload_intents",
        *identity(),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("materials.id")),
        sa.Column("object_key", sa.String(100), unique=True, nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON()),
    )
    # Browser access uses FastAPI authorization, never the public Supabase Data API.
    # Owners (local lerny role / Supabase postgres backend) continue to work.
    for table in APP_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "alembic_version" ENABLE ROW LEVEL SECURITY')


def downgrade():
    for table in APP_TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "alembic_version" DISABLE ROW LEVEL SECURITY')
    op.drop_table("upload_intents")
    op.drop_table("ai_workers")
    op.drop_table("model_calls")
