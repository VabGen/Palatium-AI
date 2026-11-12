"""Add nullable content_sha256 on attachments (W10 P0.4 integrity).

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-11-12 09:40:00.000000

Additive only: nullable, no backfill. Existing ready rows stay NULL until
complete_upload / reingest seals the digest from the stored blob.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "attachments"
COLUMN_NAME = "content_sha256"
# SHA-256 hex length — keep in sync with core.types.digest.SHA256_HEX_LENGTH.
_SHA256_HEX_LENGTH = 64


def upgrade() -> None:
    """Add content_sha256 for original-blob integrity seals."""
    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.String(_SHA256_HEX_LENGTH), nullable=True),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop content_sha256."""
    op.drop_column(TABLE_NAME, COLUMN_NAME, schema=SCHEMA_NAME)
