"""SECURITY DEFINER retention helpers + palatium_retention role (ADR 0002).

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-10-05 15:40:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
APP_SCHEMA = "palatium_ai"
APP_ROLE = "palatium_app"
RETENTION_ROLE = "palatium_retention"


def upgrade() -> None:
    """Create retention role, indexes, and RLS-bypass functions for memory sweep."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RETENTION_ROLE}') THEN
            CREATE ROLE {RETENTION_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE
              NOINHERIT NOBYPASSRLS NOREPLICATION;
          END IF;
        END
        $$;
        """
    )

    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_sessions_updated_at
        ON {APP_SCHEMA}.sessions (updated_at)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_memory_entries_expires_at
        ON {MEMORY_SCHEMA}.entries (expires_at)
        WHERE expires_at IS NOT NULL
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {MEMORY_SCHEMA}.retention_backfill_expires(
          p_medium_days integer,
          p_episode_days integer,
          p_pii_days integer,
          p_limit integer
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {MEMORY_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          IF p_medium_days < 1 OR p_episode_days < 1 OR p_pii_days < 1 OR p_limit < 1 THEN
            RAISE EXCEPTION 'retention_backfill_expires: invalid arguments';
          END IF;
          WITH candidates AS (
            SELECT id, memory_type, contains_pii, created_at
            FROM {MEMORY_SCHEMA}.entries
            WHERE expires_at IS NULL
            ORDER BY created_at ASC
            LIMIT p_limit
            FOR UPDATE SKIP LOCKED
          ),
          computed AS (
            SELECT
              id,
              created_at + make_interval(
                days => CASE
                  WHEN contains_pii THEN LEAST(
                    CASE WHEN memory_type = 'episode' THEN p_episode_days ELSE p_medium_days END,
                    p_pii_days
                  )
                  WHEN memory_type = 'episode' THEN p_episode_days
                  ELSE p_medium_days
                END
              ) AS new_expires
            FROM candidates
          )
          UPDATE {MEMORY_SCHEMA}.entries AS e
          SET expires_at = c.new_expires
          FROM computed AS c
          WHERE e.id = c.id;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {MEMORY_SCHEMA}.retention_count_expired(
          p_now timestamptz,
          p_class text DEFAULT 'all'
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {MEMORY_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          SELECT count(*)::integer INTO n
          FROM {MEMORY_SCHEMA}.entries
          WHERE expires_at IS NOT NULL
            AND expires_at <= p_now
            AND CASE p_class
              WHEN 'memory_pii' THEN contains_pii
              WHEN 'memory_episode' THEN (NOT contains_pii) AND memory_type = 'episode'
              WHEN 'memory_medium' THEN (NOT contains_pii) AND memory_type <> 'episode'
              ELSE TRUE
            END;
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {MEMORY_SCHEMA}.retention_delete_expired(
          p_now timestamptz,
          p_limit integer,
          p_class text DEFAULT 'all'
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {MEMORY_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          IF p_limit < 1 THEN
            RAISE EXCEPTION 'retention_delete_expired: p_limit must be >= 1';
          END IF;
          WITH victims AS (
            SELECT id
            FROM {MEMORY_SCHEMA}.entries
            WHERE expires_at IS NOT NULL
              AND expires_at <= p_now
              AND CASE p_class
                WHEN 'memory_pii' THEN contains_pii
                WHEN 'memory_episode' THEN (NOT contains_pii) AND memory_type = 'episode'
                WHEN 'memory_medium' THEN (NOT contains_pii) AND memory_type <> 'episode'
                ELSE TRUE
              END
            ORDER BY expires_at ASC
            LIMIT p_limit
            FOR UPDATE SKIP LOCKED
          )
          DELETE FROM {MEMORY_SCHEMA}.entries AS e
          USING victims AS v
          WHERE e.id = v.id;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END;
        $$;
        """
    )

    for fn in (
        "retention_backfill_expires(integer, integer, integer, integer)",
        "retention_count_expired(timestamptz, text)",
        "retention_delete_expired(timestamptz, integer, text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {MEMORY_SCHEMA}.{fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {MEMORY_SCHEMA}.{fn} TO {RETENTION_ROLE}")
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT EXECUTE ON FUNCTION {MEMORY_SCHEMA}.{fn} TO {APP_ROLE};
              END IF;
            END
            $$;
            """
        )
        # Migration/connection owner (often postgres) must run the job before role cutover.
        op.execute(f"GRANT EXECUTE ON FUNCTION {MEMORY_SCHEMA}.{fn} TO CURRENT_USER")

    op.execute(f"GRANT USAGE ON SCHEMA {MEMORY_SCHEMA} TO {RETENTION_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA {APP_SCHEMA} TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON {APP_SCHEMA}.sessions TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON {APP_SCHEMA}.dialog_turns TO {RETENTION_ROLE}")


def downgrade() -> None:
    """Drop retention functions and indexes; leave role in place (safe)."""
    for fn in (
        "retention_delete_expired(timestamptz, integer, text)",
        "retention_count_expired(timestamptz, text)",
        "retention_backfill_expires(integer, integer, integer, integer)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {MEMORY_SCHEMA}.{fn}")
    op.execute(f"DROP INDEX IF EXISTS {MEMORY_SCHEMA}.ix_memory_entries_expires_at")
    op.execute(f"DROP INDEX IF EXISTS {APP_SCHEMA}.ix_sessions_updated_at")
