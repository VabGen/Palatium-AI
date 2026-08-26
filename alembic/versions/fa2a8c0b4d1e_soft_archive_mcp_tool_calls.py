"""Soft-archive for mcp_tool_calls.

Revision ID: fa2a8c0b4d1e
Revises: 9d3e5f7c1a4b
Create Date: 2026-08-19 16:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "fa2a8c0b4d1e"
down_revision = "9d3e5f7c1a4b"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Add soft-archive support for `mcp_tool_calls`."""
    op.add_column(
        "mcp_tool_calls",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_mcp_tool_calls_archived_at",
        "mcp_tool_calls",
        ["archived_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Revert soft-archive support for `mcp_tool_calls`."""
    op.drop_index(
        "ix_mcp_tool_calls_archived_at",
        table_name="mcp_tool_calls",
        schema=SCHEMA_NAME,
    )
    op.drop_column("mcp_tool_calls", "archived_at", schema=SCHEMA_NAME)
