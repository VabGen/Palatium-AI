"""Durable memory extract job queue (SKIP LOCKED; Wave M3).

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-06 16:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
TABLE_NAME = "extract_jobs"


def upgrade() -> None:
    """Platform-owned extract queue (no FORCE RLS — not per-user row data)."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {MEMORY_SCHEMA}")
    op.create_table(
        TABLE_NAME,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("org_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("thread_id", "task_id", name="uq_memory_extract_jobs_thread_task"),
        schema=MEMORY_SCHEMA,
    )
    op.create_index(
        "ix_memory_extract_jobs_claim",
        TABLE_NAME,
        ["status", "available_at", "created_at"],
        schema=MEMORY_SCHEMA,
    )


def downgrade() -> None:
    """Drop extract job queue."""
    op.drop_index("ix_memory_extract_jobs_claim", table_name=TABLE_NAME, schema=MEMORY_SCHEMA)
    op.drop_table(TABLE_NAME, schema=MEMORY_SCHEMA)
