"""SECURITY DEFINER owner discovery for inferred-trust corroboration (ADR 0008).

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6
Create Date: 2026-11-03 15:20:00.000000

Promote discovery only lists promotable rows. Corroboration must also reach
tenants whose medium rows are still ``trust=inferred`` (peer-extract / overlap
upgrade before promote). Same FORCE-RLS pattern as ``promotion_owner_ids``.
"""

from __future__ import annotations

from alembic import op

revision = "l2a3b4c5d6e7"
down_revision = "k1f2a3b4c5d6"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
APP_ROLE = "palatium_app"

FUNCTION = "corroboration_owner_ids(integer)"


def upgrade() -> None:
    """Create owner-discovery RPC used by ``jobs.memory_consolidate`` corroboration."""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {MEMORY_SCHEMA}.corroboration_owner_ids(
          p_limit integer
        ) RETURNS SETOF text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {MEMORY_SCHEMA}, pg_temp
        AS $$
        BEGIN
          IF p_limit < 1 THEN
            RAISE EXCEPTION 'corroboration_owner_ids: invalid arguments';
          END IF;
          RETURN QUERY
          SELECT e.user_id::text
          FROM {MEMORY_SCHEMA}.entries AS e
          WHERE (e.expires_at IS NULL OR e.expires_at > now())
            AND e.user_id NOT LIKE 'thread:%'
            AND e.user_id NOT LIKE 'org:%'
            AND e.user_id <> 'system'
            -- Missing trust defaults to inferred (ADR 0008 legacy); skip quarantined.
            AND coalesce(e.value->>'trust', 'inferred') = 'inferred'
          GROUP BY e.user_id
          ORDER BY max(e.created_at) DESC
          LIMIT p_limit;
        END;
        $$;
        """
    )

    op.execute(f"REVOKE ALL ON FUNCTION {MEMORY_SCHEMA}.{FUNCTION} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT EXECUTE ON FUNCTION {MEMORY_SCHEMA}.{FUNCTION} TO {APP_ROLE};
          END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {MEMORY_SCHEMA}.{FUNCTION} TO CURRENT_USER")


def downgrade() -> None:
    """Drop corroboration owner-discovery RPC."""
    op.execute(f"DROP FUNCTION IF EXISTS {MEMORY_SCHEMA}.{FUNCTION}")
