"""Durable memory ops queue (SKIP LOCKED; W11).

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-11-12 20:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
TABLE_NAME = "ops"


def upgrade() -> None:
    """Platform-owned memory op queue (promote_entry / clear_user_graph)."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {MEMORY_SCHEMA}")
    op.create_table(
        TABLE_NAME,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("entry_key", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("namespace_json", sa.String(length=1024), nullable=False, server_default="[]"),
        sa.Column("reason", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        schema=MEMORY_SCHEMA,
    )
    op.create_index(
        "ix_memory_ops_claim",
        TABLE_NAME,
        ["status", "available_at", "created_at"],
        schema=MEMORY_SCHEMA,
    )


def downgrade() -> None:
    """Drop memory ops queue."""
    op.drop_index("ix_memory_ops_claim", table_name=TABLE_NAME, schema=MEMORY_SCHEMA)
    op.drop_table(TABLE_NAME, schema=MEMORY_SCHEMA)
