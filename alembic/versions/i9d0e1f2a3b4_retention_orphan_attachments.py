"""Retention RPCs for thread-less (orphan) attach rows.

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-10-19 11:05:00.000000

P0-A makes ``thread_id`` mandatory for ``mode='attach'``: every read path
(``list_for_thread``, ``get_many``, the reference resolver) is thread-scoped, so
a row written without a thread is unreachable and only occupies storage.

Rows created before that rule still exist, and a non-HTTP caller could still
write one. The retention job therefore needs a second candidate query: an
``attach`` row with a NULL/blank thread, older than the grace window, and not in
an in-flight state. ``index`` rows are excluded — they may already have written
knowledge, whose cascade must not be triggered by an orphan sweep (060).

The partial index keeps that lookup cheap: it only covers the rows the query can
ever match, so it stays small even as the table grows.
"""

from __future__ import annotations

from alembic import op

revision = "i9d0e1f2a3b4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None

APP_SCHEMA = "palatium_ai"
APP_ROLE = "palatium_app"
RETENTION_ROLE = "palatium_retention"

#: States a row can still leave on its own. ``pending`` is owned by the
#: ticket-expiry rule; ``uploaded``/``scanning`` belong to ``complete``.
_IN_FLIGHT_STATES = "'pending', 'uploaded', 'scanning'"


def upgrade() -> None:
    """Add orphan-scoped list/count RPCs plus their partial index."""
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_attachments_attach_orphan_created_at
        ON {APP_SCHEMA}.attachments (created_at)
        WHERE mode = 'attach'
          AND coalesce(btrim(thread_id), '') = ''
          AND status NOT IN ({_IN_FLIGHT_STATES})
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {APP_SCHEMA}.retention_list_orphan_attachments(
          p_orphan_before timestamptz,
          p_limit integer,
          p_class text DEFAULT 'all'
        ) RETURNS TABLE (
          id uuid,
          user_id text,
          blob_key text,
          derived_text_key text,
          mode text,
          status text,
          project_id text,
          contains_pii boolean,
          expires_at timestamptz,
          created_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {APP_SCHEMA}, pg_temp
        AS $$
        BEGIN
          IF p_limit < 1 THEN
            RAISE EXCEPTION 'retention_list_orphan_attachments: p_limit must be >= 1';
          END IF;
          RETURN QUERY
          SELECT
            a.id,
            a.user_id,
            a.blob_key,
            a.derived_text_key,
            a.mode,
            a.status,
            a.project_id,
            a.contains_pii,
            a.expires_at,
            a.created_at
          FROM {APP_SCHEMA}.attachments AS a
          WHERE a.mode = 'attach'
            AND (a.thread_id IS NULL OR btrim(a.thread_id) = '')
            AND a.status NOT IN ({_IN_FLIGHT_STATES})
            AND a.created_at <= p_orphan_before
            AND CASE p_class
              WHEN 'attachment_pii' THEN a.contains_pii
              WHEN 'attachment_attach' THEN (NOT a.contains_pii)
              WHEN 'attachment_index' THEN FALSE
              ELSE TRUE
            END
          ORDER BY a.created_at ASC
          LIMIT p_limit;
          -- No FOR UPDATE: blob I/O happens outside the DB transaction (080).
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {APP_SCHEMA}.retention_count_orphan_attachments(
          p_orphan_before timestamptz,
          p_class text DEFAULT 'all'
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {APP_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          SELECT count(*)::integer INTO n
          FROM {APP_SCHEMA}.attachments AS a
          WHERE a.mode = 'attach'
            AND (a.thread_id IS NULL OR btrim(a.thread_id) = '')
            AND a.status NOT IN ({_IN_FLIGHT_STATES})
            AND a.created_at <= p_orphan_before
            AND CASE p_class
              WHEN 'attachment_pii' THEN a.contains_pii
              WHEN 'attachment_attach' THEN (NOT a.contains_pii)
              WHEN 'attachment_index' THEN FALSE
              ELSE TRUE
            END;
          RETURN n;
        END;
        $$;
        """
    )

    for fn in (
        "retention_list_orphan_attachments(timestamptz, integer, text)",
        "retention_count_orphan_attachments(timestamptz, text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {APP_SCHEMA}.{fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {APP_SCHEMA}.{fn} TO {RETENTION_ROLE}")
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT EXECUTE ON FUNCTION {APP_SCHEMA}.{fn} TO {APP_ROLE};
              END IF;
            END
            $$
            """
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {APP_SCHEMA}.{fn} TO CURRENT_USER")


def downgrade() -> None:
    """Drop the orphan RPCs and their partial index."""
    for fn in (
        "retention_count_orphan_attachments(timestamptz, text)",
        "retention_list_orphan_attachments(timestamptz, integer, text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {APP_SCHEMA}.{fn}")
    op.execute(f"DROP INDEX IF EXISTS {APP_SCHEMA}.ix_attachments_attach_orphan_created_at")
