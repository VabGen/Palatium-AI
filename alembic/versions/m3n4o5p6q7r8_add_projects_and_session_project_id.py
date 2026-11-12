"""Add projects table (FORCE RLS) and sessions.project_id.

Revision ID: m3n4o5p6q7r8
Revises: l2a3b4c5d6e7
Create Date: 2026-11-06 14:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m3n4o5p6q7r8"
down_revision = "l2a3b4c5d6e7"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
PROJECTS_TABLE = "projects"
SESSIONS_TABLE = "sessions"
APP_ROLE = "palatium_app"
POLICY_NAME = "projects_user_isolation"

# Fail-closed: unset/empty palatium.user_id → no rows (060).
_POLICY_PREDICATE = (
    "nullif(current_setting('palatium.user_id', true), '') IS NOT NULL AND user_id = current_setting('palatium.user_id', true)"
)


def upgrade() -> None:
    """Create projects + RLS; add nullable sessions.project_id."""
    op.create_table(
        PROJECTS_TABLE,
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_projects_user_updated_at",
        PROJECTS_TABLE,
        ["user_id", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.execute(f"ALTER TABLE {SCHEMA_NAME}.{PROJECTS_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA_NAME}.{PROJECTS_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON {SCHEMA_NAME}.{PROJECTS_TABLE}
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
            GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA_NAME}.{PROJECTS_TABLE} TO {APP_ROLE};
          END IF;
        END
        $$;
        """
    )

    op.add_column(
        SESSIONS_TABLE,
        sa.Column("project_id", sa.String(length=128), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_sessions_user_project",
        SESSIONS_TABLE,
        ["user_id", "project_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    """Drop sessions.project_id and projects table."""
    op.drop_index("ix_sessions_user_project", table_name=SESSIONS_TABLE, schema=SCHEMA_NAME)
    op.drop_column(SESSIONS_TABLE, "project_id", schema=SCHEMA_NAME)
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {SCHEMA_NAME}.{PROJECTS_TABLE}")
    op.drop_index("ix_projects_user_updated_at", table_name=PROJECTS_TABLE, schema=SCHEMA_NAME)
    op.drop_table(PROJECTS_TABLE, schema=SCHEMA_NAME)
