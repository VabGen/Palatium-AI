"""Repair missing mcp_tool_calls columns for legacy databases.

Revision ID: a1b2c3d4e5f6
Revises: fa2a8c0b4d1e
Create Date: 2026-08-20 11:45:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "fa2a8c0b4d1e"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"


def upgrade() -> None:
    """Add session_id/archived_at when table was created before latest schema."""
    op.execute(
        f"""
        ALTER TABLE {SCHEMA_NAME}.mcp_tool_calls
        ADD COLUMN IF NOT EXISTS session_id UUID;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA_NAME}.mcp_tool_calls
        ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            ALTER TABLE {SCHEMA_NAME}.mcp_tool_calls
            ADD CONSTRAINT fk_mcp_tool_calls_session_id_sessions
            FOREIGN KEY (session_id)
            REFERENCES {SCHEMA_NAME}.sessions(id)
            ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_session_id_created_at
        ON {SCHEMA_NAME}.mcp_tool_calls (session_id, created_at);
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_archived_at
        ON {SCHEMA_NAME}.mcp_tool_calls (archived_at);
        """
    )


def downgrade() -> None:
    """Best-effort rollback for repair migration."""
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA_NAME}.ix_mcp_tool_calls_archived_at;")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA_NAME}.ix_mcp_tool_calls_session_id_created_at;")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA_NAME}.mcp_tool_calls
        DROP CONSTRAINT IF EXISTS fk_mcp_tool_calls_session_id_sessions;
        """
    )
    op.drop_column("mcp_tool_calls", "archived_at", schema=SCHEMA_NAME)
    op.drop_column("mcp_tool_calls", "session_id", schema=SCHEMA_NAME)
