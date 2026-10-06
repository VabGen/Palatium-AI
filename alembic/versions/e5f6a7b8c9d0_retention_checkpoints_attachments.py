"""Retention RPCs for attachments, knowledge cascade, checkpoint grants.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-05 16:10:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

APP_SCHEMA = "palatium_ai"
KNOWLEDGE_SCHEMA = "knowledge"
APP_ROLE = "palatium_app"
RETENTION_ROLE = "palatium_retention"


def upgrade() -> None:
    """Indexes + SECURITY DEFINER list/delete for attachments and knowledge."""
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_attachments_expires_at
        ON {APP_SCHEMA}.attachments (expires_at)
        WHERE expires_at IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_knowledge_documents_source_document_id
        ON {KNOWLEDGE_SCHEMA}.documents (source_document_id)
        WHERE source_document_id IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_knowledge_documents_updated_at
        ON {KNOWLEDGE_SCHEMA}.documents (updated_at)
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {APP_SCHEMA}.retention_list_reclaimable_attachments(
          p_now timestamptz,
          p_pending_before timestamptz,
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
            RAISE EXCEPTION 'retention_list_reclaimable_attachments: p_limit must be >= 1';
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
          WHERE (
              (a.status = 'pending' AND a.created_at <= p_pending_before)
              OR (a.expires_at IS NOT NULL AND a.expires_at <= p_now)
            )
            AND CASE p_class
              WHEN 'attachment_pii' THEN a.contains_pii
              WHEN 'attachment_attach' THEN (NOT a.contains_pii) AND a.mode = 'attach'
              WHEN 'attachment_index' THEN (NOT a.contains_pii) AND a.mode = 'index'
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
        CREATE OR REPLACE FUNCTION {APP_SCHEMA}.retention_count_reclaimable_attachments(
          p_now timestamptz,
          p_pending_before timestamptz,
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
          WHERE (
              (a.status = 'pending' AND a.created_at <= p_pending_before)
              OR (a.expires_at IS NOT NULL AND a.expires_at <= p_now)
            )
            AND CASE p_class
              WHEN 'attachment_pii' THEN a.contains_pii
              WHEN 'attachment_attach' THEN (NOT a.contains_pii) AND a.mode = 'attach'
              WHEN 'attachment_index' THEN (NOT a.contains_pii) AND a.mode = 'index'
              ELSE TRUE
            END;
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {APP_SCHEMA}.retention_delete_attachment(
          p_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {APP_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          DELETE FROM {APP_SCHEMA}.attachments WHERE id = p_id;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {KNOWLEDGE_SCHEMA}.retention_delete_by_attachment(
          p_attachment_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {KNOWLEDGE_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
          hex_id text := replace(p_attachment_id::text, '-', '');
        BEGIN
          DELETE FROM {KNOWLEDGE_SCHEMA}.documents AS d
          WHERE d.source_document_id = p_attachment_id::text
             OR (
               d.source_document_id LIKE 'project:%'
               AND right(d.source_document_id, 32) = hex_id
             );
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {KNOWLEDGE_SCHEMA}.retention_count_orphans(
          p_cutoff timestamptz
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {KNOWLEDGE_SCHEMA}, {APP_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          SELECT count(*)::integer INTO n
          FROM {KNOWLEDGE_SCHEMA}.documents AS d
          WHERE d.updated_at < p_cutoff
            AND NOT EXISTS (
              SELECT 1
              FROM {APP_SCHEMA}.attachments AS a
              WHERE d.source_document_id = a.id::text
                 OR (
                   d.source_document_id LIKE 'project:%'
                   AND right(d.source_document_id, 32) = replace(a.id::text, '-', '')
                 )
            );
          RETURN n;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {KNOWLEDGE_SCHEMA}.retention_delete_orphans(
          p_cutoff timestamptz,
          p_limit integer
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = {KNOWLEDGE_SCHEMA}, {APP_SCHEMA}, pg_temp
        AS $$
        DECLARE
          n integer := 0;
        BEGIN
          IF p_limit < 1 THEN
            RAISE EXCEPTION 'retention_delete_orphans: p_limit must be >= 1';
          END IF;
          WITH victims AS (
            SELECT d.id
            FROM {KNOWLEDGE_SCHEMA}.documents AS d
            WHERE d.updated_at < p_cutoff
              AND NOT EXISTS (
                SELECT 1
                FROM {APP_SCHEMA}.attachments AS a
                WHERE d.source_document_id = a.id::text
                   OR (
                     d.source_document_id LIKE 'project:%'
                     AND right(d.source_document_id, 32) = replace(a.id::text, '-', '')
                   )
              )
            ORDER BY d.updated_at ASC
            LIMIT p_limit
            FOR UPDATE OF d SKIP LOCKED
          )
          DELETE FROM {KNOWLEDGE_SCHEMA}.documents AS d
          USING victims AS v
          WHERE d.id = v.id;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END;
        $$;
        """
    )

    for schema, fn in (
        (
            APP_SCHEMA,
            "retention_list_reclaimable_attachments(timestamptz, timestamptz, integer, text)",
        ),
        (
            APP_SCHEMA,
            "retention_count_reclaimable_attachments(timestamptz, timestamptz, text)",
        ),
        (APP_SCHEMA, "retention_delete_attachment(uuid)"),
        (KNOWLEDGE_SCHEMA, "retention_delete_by_attachment(uuid)"),
        (KNOWLEDGE_SCHEMA, "retention_count_orphans(timestamptz)"),
        (KNOWLEDGE_SCHEMA, "retention_delete_orphans(timestamptz, integer)"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {schema}.{fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {schema}.{fn} TO {RETENTION_ROLE}")
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT EXECUTE ON FUNCTION {schema}.{fn} TO {APP_ROLE};
              END IF;
            END
            $$;
            """
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {schema}.{fn} TO CURRENT_USER")

    op.execute(f"GRANT USAGE ON SCHEMA {KNOWLEDGE_SCHEMA} TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON {APP_SCHEMA}.attachments TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON {KNOWLEDGE_SCHEMA}.documents TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON {KNOWLEDGE_SCHEMA}.chunks TO {RETENTION_ROLE}")

    # LangGraph AsyncPostgresSaver tables live in public (created by setup()).
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(
            f"""
            DO $$
            BEGIN
              IF to_regclass('public.{table}') IS NOT NULL THEN
                EXECUTE 'GRANT SELECT, DELETE ON public.{table} TO {RETENTION_ROLE}';
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                  EXECUTE 'GRANT SELECT, DELETE ON public.{table} TO {APP_ROLE}';
                END IF;
              END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    """Drop attachment/knowledge retention functions and indexes."""
    for schema, fn in (
        (KNOWLEDGE_SCHEMA, "retention_delete_orphans(timestamptz, integer)"),
        (KNOWLEDGE_SCHEMA, "retention_count_orphans(timestamptz)"),
        (KNOWLEDGE_SCHEMA, "retention_delete_by_attachment(uuid)"),
        (APP_SCHEMA, "retention_delete_attachment(uuid)"),
        (
            APP_SCHEMA,
            "retention_count_reclaimable_attachments(timestamptz, timestamptz, text)",
        ),
        (
            APP_SCHEMA,
            "retention_list_reclaimable_attachments(timestamptz, timestamptz, integer, text)",
        ),
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {schema}.{fn}")
    op.execute(f"DROP INDEX IF EXISTS {KNOWLEDGE_SCHEMA}.ix_knowledge_documents_updated_at")
    op.execute(f"DROP INDEX IF EXISTS {KNOWLEDGE_SCHEMA}.ix_knowledge_documents_source_document_id")
    op.execute(f"DROP INDEX IF EXISTS {APP_SCHEMA}.ix_attachments_expires_at")
