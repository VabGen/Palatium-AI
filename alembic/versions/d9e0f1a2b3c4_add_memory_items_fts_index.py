"""Add GIN FTS index on memory_items.search_text (hybrid retrieve).

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-20 23:05:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Create GIN FTS index on memory_items.search_text."""
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_memory_items_search_fts
        ON {SCHEMA_NAME}.memory_items
        USING GIN (to_tsvector('simple', search_text))
        """
    )


def downgrade() -> None:
    """Drop GIN FTS index on memory_items.search_text."""
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA_NAME}.ix_memory_items_search_fts")
