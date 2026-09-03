"""Add memory.entries with pgvector, FTS and RLS (060).

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-09-02 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
MEMORY_EMBEDDING_DIM = 384


def upgrade() -> None:
    """Create memory schema, entries table, indexes and RLS."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {MEMORY_SCHEMA}")

    op.create_table(
        "entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("namespace", sa.String(length=512), nullable=False),
        sa.Column("entry_key", sa.String(length=256), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False, server_default="fact"),
        sa.Column(
            "value", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("contains_pii", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("user_id", "namespace", "entry_key", name="uq_memory_entries_user_ns_key"),
        schema=MEMORY_SCHEMA,
    )

    op.execute(
        f"""
        ALTER TABLE {MEMORY_SCHEMA}.entries
        ADD COLUMN embedding vector({MEMORY_EMBEDDING_DIM})
        """
    )

    op.create_index(
        "ix_memory_entries_user_namespace",
        "entries",
        ["user_id", "namespace"],
        schema=MEMORY_SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_memory_entries_search_fts
        ON {MEMORY_SCHEMA}.entries
        USING GIN (to_tsvector('simple', search_text))
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw
        ON {MEMORY_SCHEMA}.entries
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )

    op.execute(f"ALTER TABLE {MEMORY_SCHEMA}.entries ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {MEMORY_SCHEMA}.entries FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries
        FOR ALL
        USING (user_id = current_setting('palatium.user_id', true))
        WITH CHECK (user_id = current_setting('palatium.user_id', true))
        """
    )


def downgrade() -> None:
    """Drop memory.entries and schema."""
    op.execute(f"DROP POLICY IF EXISTS memory_entries_user_isolation ON {MEMORY_SCHEMA}.entries")
    op.drop_index("ix_memory_entries_user_namespace", table_name="entries", schema=MEMORY_SCHEMA)
    op.execute(f"DROP INDEX IF EXISTS {MEMORY_SCHEMA}.ix_memory_entries_search_fts")
    op.execute(f"DROP INDEX IF EXISTS {MEMORY_SCHEMA}.ix_memory_entries_embedding_hnsw")
    op.drop_table("entries", schema=MEMORY_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {MEMORY_SCHEMA}")
