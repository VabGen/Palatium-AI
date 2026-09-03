"""Harden RLS policies + create palatium_app role without BYPASSRLS (060).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-02 20:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
KNOWLEDGE_SCHEMA = "knowledge"
APP_ROLE = "palatium_app"

_POLICY_PREDICATE = (
    "nullif(current_setting('palatium.user_id', true), '') IS NOT NULL "
    "AND user_id = current_setting('palatium.user_id', true)"
)


def upgrade() -> None:
    """Fail-closed RLS predicates + non-BYPASSRLS app role with grants."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE
              NOINHERIT NOBYPASSRLS NOREPLICATION;
          ELSE
            ALTER ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS;
          END IF;
        END
        $$;
        """
    )

    op.execute(f"DROP POLICY IF EXISTS memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries")
    op.execute(
        f"""
        CREATE POLICY memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries
        FOR ALL
        USING ({_POLICY_PREDICATE})
        WITH CHECK ({_POLICY_PREDICATE})
        """
    )

    for table in ("documents", "chunks"):
        op.execute(f"DROP POLICY IF EXISTS knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}")
        op.execute(
            f"""
            CREATE POLICY knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}
            FOR ALL
            USING ({_POLICY_PREDICATE})
            WITH CHECK ({_POLICY_PREDICATE})
            """
        )

    for schema in (MEMORY_SCHEMA, KNOWLEDGE_SCHEMA):
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {APP_ROLE}")
        op.execute(
            f"""
            ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}
            """
        )


def downgrade() -> None:
    """Restore prior RLS predicates; leave app role in place (safe)."""
    simple = "user_id = current_setting('palatium.user_id', true)"

    op.execute(f"DROP POLICY IF EXISTS memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries")
    op.execute(
        f"""
        CREATE POLICY memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries
        FOR ALL
        USING ({simple})
        WITH CHECK ({simple})
        """
    )

    for table in ("documents", "chunks"):
        op.execute(f"DROP POLICY IF EXISTS knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}")
        op.execute(
            f"""
            CREATE POLICY knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}
            FOR ALL
            USING ({simple})
            WITH CHECK ({simple})
            """
        )
