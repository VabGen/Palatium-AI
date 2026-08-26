"""Add dialog_turns table for transcript memory (P0).

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-20 22:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Create dialog_turns table."""
    op.create_table(
        "dialog_turns",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            [f"{SCHEMA_NAME}.sessions.id"],
            name="fk_dialog_turns_session_id_sessions",
            ondelete="SET NULL",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_dialog_turns_thread_seq",
        "dialog_turns",
        ["thread_id", "seq"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_dialog_turns_thread_created",
        "dialog_turns",
        ["thread_id", "created_at"],
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Remove dialog_turns table."""
    op.drop_index("ix_dialog_turns_thread_created", table_name="dialog_turns", schema=SCHEMA_NAME)
    op.drop_index("ix_dialog_turns_thread_seq", table_name="dialog_turns", schema=SCHEMA_NAME)
    op.drop_table("dialog_turns", schema=SCHEMA_NAME)
