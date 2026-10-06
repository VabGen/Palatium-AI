"""Add contains_pii flag to attachments for G06 UI/audit surfacing.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-05 11:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "attachments"


def upgrade() -> None:
    """Persist extracted-text PII classification on the metadata row."""
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "contains_pii",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop contains_pii column."""
    op.drop_column(TABLE_NAME, "contains_pii", schema=SCHEMA_NAME)
