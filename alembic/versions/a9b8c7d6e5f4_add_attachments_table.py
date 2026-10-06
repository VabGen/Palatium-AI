"""Add attachments table with fail-closed RLS.

Revision ID: a9b8c7d6e5f4
Revises: f7a8b9c0d1e2
Create Date: 2026-09-25 17:10:00.000000

Scope note: this migration grants ``palatium_app`` access to ``attachments`` only.
The other tables in the ``palatium_ai`` schema (``sessions``, ``mcp_tool_calls``,
``dialog_turns``, ``memory_items``) still rely on explicit ``user_id`` predicates
without RLS — that gap is tracked separately and is not widened here.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a9b8c7d6e5f4"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "attachments"
APP_ROLE = "palatium_app"
POLICY_NAME = "attachments_user_isolation"

# Fail-closed: an unset *or empty* scope makes the predicate false, so a session
# that forgot to bind palatium.user_id sees no rows instead of every row (060).
_POLICY_PREDICATE = (
    "nullif(current_setting('palatium.user_id', true), '') IS NOT NULL "
    "AND user_id = current_setting('palatium.user_id', true)"
)


def upgrade() -> None:
    """Create the attachments table, force RLS on it, and grant the app role."""
    op.create_table(
        TABLE_NAME,
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("blob_key", sa.String(length=512), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("derived_text_key", sa.String(length=512), nullable=True),
        sa.Column("rejection_reason", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("blob_key", name=op.f("uq_attachments_blob_key")),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_attachments_thread_created_at",
        TABLE_NAME,
        ["thread_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_attachments_user_status",
        TABLE_NAME,
        ["user_id", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    # ENABLE alone would exempt the table owner; FORCE subjects owner connections
    # to the policy too, which is why the repository always binds the scope (060).
    op.execute(f"ALTER TABLE {SCHEMA_NAME}.{TABLE_NAME} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA_NAME}.{TABLE_NAME} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON {SCHEMA_NAME}.{TABLE_NAME}
        FOR ALL
        USING ({_POLICY_PREDICATE})
        WITH CHECK ({_POLICY_PREDICATE})
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO {APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA_NAME}.{TABLE_NAME} TO {APP_ROLE};
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Drop the attachments table and its policy."""
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {SCHEMA_NAME}.{TABLE_NAME}")
    op.drop_index("ix_attachments_user_status", table_name=TABLE_NAME, schema=SCHEMA_NAME)
    op.drop_index("ix_attachments_thread_created_at", table_name=TABLE_NAME, schema=SCHEMA_NAME)
    op.drop_table(TABLE_NAME, schema=SCHEMA_NAME)
