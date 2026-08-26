"""Add sessions table.

Revision ID: 5f3d4c2b1a00
Revises: c48be75a5467
Create Date: 2026-08-19 16:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "5f3d4c2b1a00"
down_revision = "c48be75a5467"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Create the primary sessions table in the application schema."""
    op.create_table(
        "sessions",
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', now())"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("thread_id", name=op.f("uq_sessions_thread_id")),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_sessions_status_created_at",
        "sessions",
        ["status", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop the sessions table and its supporting index."""
    op.drop_index("ix_sessions_status_created_at", table_name="sessions", schema=SCHEMA_NAME)
    op.drop_table("sessions", schema=SCHEMA_NAME)
