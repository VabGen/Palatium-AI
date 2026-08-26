"""Add mcp tool calls table.

Revision ID: 9d3e5f7c1a4b
Revises: 5f3d4c2b1a00
Create Date: 2026-08-19 16:25:00.000000
"""

from __future__ import annotations
# ruff: noqa: I001

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "9d3e5f7c1a4b"
down_revision = "5f3d4c2b1a00"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Upgrade the database to the next version."""
    op.create_table(
        "mcp_tool_calls",
        sa.Column("conversation_id", sa.String(length=256), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("server_name", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_error",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', now())"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            [f"{SCHEMA_NAME}.sessions.id"],
            name=op.f("fk_mcp_tool_calls_session_id_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_tool_calls")),
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_mcp_tool_calls_conversation_id_created_at",
        "mcp_tool_calls",
        ["conversation_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_mcp_tool_calls_session_id_created_at",
        "mcp_tool_calls",
        ["session_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Downgrade the database to the previous version."""
    op.drop_index(
        "ix_mcp_tool_calls_session_id_created_at",
        table_name="mcp_tool_calls",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_mcp_tool_calls_conversation_id_created_at",
        table_name="mcp_tool_calls",
        schema=SCHEMA_NAME,
    )
    op.drop_table("mcp_tool_calls", schema=SCHEMA_NAME)
