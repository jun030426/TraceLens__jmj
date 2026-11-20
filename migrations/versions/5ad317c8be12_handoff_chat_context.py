"""Authenticated learning context and one mutable feedback per answer.

Revision ID: 5ad317c8be12
Revises: 2912e67e0d27
"""
from alembic import op
import sqlalchemy as sa

revision = "5ad317c8be12"
down_revision = "2912e67e0d27"
branch_labels = None
depends_on = None


def upgrade():
    # Existing server-only table retains its RLS/grants; no browser DB access.
    op.add_column("chat_messages", sa.Column("learning_context", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("chat_messages", sa.Column("feedback", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_messages", "feedback")
    op.drop_column("chat_messages", "learning_context")
