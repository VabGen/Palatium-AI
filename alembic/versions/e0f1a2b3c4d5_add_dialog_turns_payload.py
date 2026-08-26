"""Add payload JSONB to dialog_turns for structured ContentDocument hydrate.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-08-20 23:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Add payload JSONB to dialog_turns for structured ContentDocument hydrate."""
    op.add_column(
        "dialog_turns",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop payload JSONB from dialog_turns."""
    op.drop_column("dialog_turns", "payload", schema=SCHEMA_NAME)
