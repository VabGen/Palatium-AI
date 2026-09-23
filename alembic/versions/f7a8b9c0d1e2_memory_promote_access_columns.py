"""Add access_frequency / last_accessed / promoted_at for medium→graph promote (060).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-03 21:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"


def upgrade() -> None:
    op.add_column(
        "entries",
        sa.Column("access_frequency", sa.Integer(), nullable=False, server_default="0"),
        schema=MEMORY_SCHEMA,
    )
    op.add_column(
        "entries",
        sa.Column("last_accessed", sa.DateTime(timezone=True), nullable=True),
        schema=MEMORY_SCHEMA,
    )
    op.add_column(
        "entries",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        schema=MEMORY_SCHEMA,
    )
    op.create_index(
        "ix_memory_entries_promote_gate",
        "entries",
        ["access_frequency", "importance", "promoted_at"],
        schema=MEMORY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_memory_entries_promote_gate", table_name="entries", schema=MEMORY_SCHEMA)
    op.drop_column("entries", "promoted_at", schema=MEMORY_SCHEMA)
    op.drop_column("entries", "last_accessed", schema=MEMORY_SCHEMA)
    op.drop_column("entries", "access_frequency", schema=MEMORY_SCHEMA)
