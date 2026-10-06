"""Add optional project_id to attachments for project-scoped KB (G09).

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-10-05 10:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "attachments"


def upgrade() -> None:
    """Nullable project scope; empty means thread/global knowledge."""
    op.add_column(
        TABLE_NAME,
        sa.Column("project_id", sa.String(length=128), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_attachments_user_project",
        TABLE_NAME,
        ["user_id", "project_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop project scope column."""
    op.drop_index("ix_attachments_user_project", table_name=TABLE_NAME, schema=SCHEMA_NAME)
    op.drop_column(TABLE_NAME, "project_id", schema=SCHEMA_NAME)
