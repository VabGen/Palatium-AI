"""Add nullable extraction-state columns on attachments.

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-10-12 15:55:00.000000

Additive only: nullable, no backfill, no server defaults. Existing rows stay
NULL until ``platform.read_attachment`` / pipeline write-through stamps them.
Text SoT remains the derived blob (``derived_text_key``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "attachments"


def upgrade() -> None:
    """Add ocr_applied / extract_status / extracted_chars for observability."""
    op.add_column(
        TABLE_NAME,
        sa.Column("ocr_applied", sa.Boolean(), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("extract_status", sa.Text(), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("extracted_chars", sa.Integer(), nullable=True),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop extraction-state columns."""
    op.drop_column(TABLE_NAME, "extracted_chars", schema=SCHEMA_NAME)
    op.drop_column(TABLE_NAME, "extract_status", schema=SCHEMA_NAME)
    op.drop_column(TABLE_NAME, "ocr_applied", schema=SCHEMA_NAME)
