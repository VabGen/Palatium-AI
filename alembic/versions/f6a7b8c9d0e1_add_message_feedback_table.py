"""Add message_feedback table with FORCE RLS (web-embed §5 п.17).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-05 16:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

SCHEMA_NAME = "palatium_ai"
TABLE_NAME = "message_feedback"
APP_ROLE = "palatium_app"
POLICY_NAME = "message_feedback_user_isolation"

_POLICY_PREDICATE = (
    "nullif(current_setting('palatium.user_id', true), '') IS NOT NULL "
    "AND user_id = current_setting('palatium.user_id', true)"
)


def upgrade() -> None:
    """Create message_feedback for like/dislike persistence (060 RLS)."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("org_id", sa.String(length=128), nullable=True),
        sa.Column("rating", sa.String(length=16), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_feedback")),
        sa.UniqueConstraint(
            "user_id",
            "message_id",
            name=op.f("uq_message_feedback_user_message"),
        ),
        sa.CheckConstraint(
            "rating IN ('like', 'dislike')",
            name=op.f("ck_message_feedback_rating"),
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_message_feedback_thread_created_at",
        TABLE_NAME,
        ["thread_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_message_feedback_user_updated_at",
        TABLE_NAME,
        ["user_id", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )

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
            GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA_NAME}.{TABLE_NAME}
              TO {APP_ROLE};
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Drop message_feedback and its RLS policy."""
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {SCHEMA_NAME}.{TABLE_NAME}")
    op.drop_index(
        "ix_message_feedback_user_updated_at",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_message_feedback_thread_created_at",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_table(TABLE_NAME, schema=SCHEMA_NAME)
