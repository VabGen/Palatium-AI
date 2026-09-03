"""Add knowledge.documents + knowledge.chunks with pgvector and RLS (060).

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-02 14:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

KNOWLEDGE_SCHEMA = "knowledge"
KNOWLEDGE_EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {KNOWLEDGE_SCHEMA}")

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
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
        schema=KNOWLEDGE_SCHEMA,
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{KNOWLEDGE_SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("contextual_prefix", sa.Text(), nullable=False, server_default=""),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_doc_index"),
        schema=KNOWLEDGE_SCHEMA,
    )

    op.execute(
        f"""
        ALTER TABLE {KNOWLEDGE_SCHEMA}.chunks
        ADD COLUMN embedding vector({KNOWLEDGE_EMBEDDING_DIM})
        """
    )

    op.create_index(
        "ix_knowledge_documents_user_thread",
        "documents",
        ["user_id", "thread_id"],
        schema=KNOWLEDGE_SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_search_fts
        ON {KNOWLEDGE_SCHEMA}.chunks
        USING GIN (to_tsvector('simple', search_text))
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw
        ON {KNOWLEDGE_SCHEMA}.chunks
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )

    for table in ("documents", "chunks"):
        op.execute(f"ALTER TABLE {KNOWLEDGE_SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {KNOWLEDGE_SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}
            FOR ALL
            USING (user_id = current_setting('palatium.user_id', true))
            WITH CHECK (user_id = current_setting('palatium.user_id', true))
            """
        )


def downgrade() -> None:
    for table in ("chunks", "documents"):
        op.execute(f"DROP POLICY IF EXISTS knowledge_{table}_user_isolation ON {KNOWLEDGE_SCHEMA}.{table}")
    op.execute(f"DROP INDEX IF EXISTS {KNOWLEDGE_SCHEMA}.ix_knowledge_chunks_embedding_hnsw")
    op.execute(f"DROP INDEX IF EXISTS {KNOWLEDGE_SCHEMA}.ix_knowledge_chunks_search_fts")
    op.drop_index("ix_knowledge_documents_user_thread", table_name="documents", schema=KNOWLEDGE_SCHEMA)
    op.drop_table("chunks", schema=KNOWLEDGE_SCHEMA)
    op.drop_table("documents", schema=KNOWLEDGE_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {KNOWLEDGE_SCHEMA}")
