"""SECURITY DEFINER owner discovery for the out-of-band memory promote job.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-10-19 16:10:00.000000

``memory.entries`` runs under ``FORCE ROW LEVEL SECURITY`` (060): a scheduler
connection with the app role sees only its own owner scope, so a promote job
that needs "every owner with promotable rows" cannot discover tenants with a
plain ``SELECT DISTINCT user_id``. Reading the ids cross-tenant is a narrow,
privileged read with no payload exposure — same pattern as the retention RPCs
(ADR 0002): SECURITY DEFINER, pinned ``search_path``, explicit grants.
"""

from __future__ import annotations

from alembic import op

revision = "j0e1f2a3b4c5"
down_revision = "i9d0e1f2a3b4"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
APP_ROLE = "palatium_app"

FUNCTION = "promotion_owner_ids(double precision, integer)"


def upgrade() -> None:
    """Create owner-discovery RPC used by ``jobs.memory_promote --all-users``."""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {MEMORY_SCHEMA}.promotion_owner_ids(
          p_min_importance double precision,
          p_limit integer
        ) RETURNS SETOF text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {MEMORY_SCHEMA}, pg_temp
        AS $$
        BEGIN
          IF p_limit < 1 OR p_min_importance < 0 THEN
            RAISE EXCEPTION 'promotion_owner_ids: invalid arguments';
          END IF;
          RETURN QUERY
          SELECT e.user_id::text
          FROM {MEMORY_SCHEMA}.entries AS e
          WHERE e.promoted_at IS NULL
            AND e.importance >= p_min_importance
            AND (e.expires_at IS NULL OR e.expires_at > now())
            -- Long-term facts are per user: thread/org/system scopes are working
            -- memory and would become graph nodes no user query can reach.
            AND e.user_id NOT LIKE 'thread:%'
            AND e.user_id NOT LIKE 'org:%'
            AND e.user_id <> 'system'
          GROUP BY e.user_id
          ORDER BY max(e.created_at) DESC
          LIMIT p_limit;
        END;
        $$;
        """
    )

    op.execute(f"REVOKE ALL ON FUNCTION {MEMORY_SCHEMA}.{FUNCTION} FROM PUBLIC")
    # Ids only, never memory payload — the promote job still reads rows per owner
    # under normal RLS in ``PostgresMemoryPort.list_promotion_candidates``.
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
    """Drop the owner-discovery RPC; the promote job falls back to explicit ids."""
    op.execute(f"DROP FUNCTION IF EXISTS {MEMORY_SCHEMA}.{FUNCTION}")
