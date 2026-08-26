"""Add memory_items table for cross-thread MemoryPort (P2).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-08-20 22:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Create memory_items table."""
    op.create_table(
        "memory_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("namespace", sa.String(length=512), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("namespace", "key", name="uq_memory_items_namespace_key"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_memory_items_namespace",
        "memory_items",
        ["namespace"],
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Remove memory_items table."""
    op.drop_index("ix_memory_items_namespace", table_name="memory_items", schema=SCHEMA_NAME)
    op.drop_table("memory_items", schema=SCHEMA_NAME)
