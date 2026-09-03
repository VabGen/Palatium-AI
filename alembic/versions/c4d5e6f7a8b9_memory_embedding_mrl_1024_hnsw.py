"""Memory embeddings: Qwen3-Embedding-8B Matryoshka 1024d + HNSW (060).

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-03 11:15:00.000000

Native model width is 4096; we store MRL truncation at 1024 so float32 HNSW
(pgvector cap 2000) is available — 2026 retrieval best practice for episodic memory.
"""

from __future__ import annotations

from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
OLD_DIM = 384
NEW_DIM = 1024


def upgrade() -> None:
    """Clear stale vectors, set column to 1024d, create HNSW cosine index."""
    op.execute(f"DROP INDEX IF EXISTS {MEMORY_SCHEMA}.ix_memory_entries_embedding_hnsw")
    op.execute(
        f"""
        UPDATE {MEMORY_SCHEMA}.entries
        SET embedding = NULL
        WHERE embedding IS NOT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE {MEMORY_SCHEMA}.entries
        ALTER COLUMN embedding TYPE vector({NEW_DIM})
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw
        ON {MEMORY_SCHEMA}.entries
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    """Restore 384d column + HNSW (vectors cleared — reindex after downgrade)."""
    op.execute(f"DROP INDEX IF EXISTS {MEMORY_SCHEMA}.ix_memory_entries_embedding_hnsw")
    op.execute(
        f"""
        UPDATE {MEMORY_SCHEMA}.entries
        SET embedding = NULL
        WHERE embedding IS NOT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE {MEMORY_SCHEMA}.entries
        ALTER COLUMN embedding TYPE vector({OLD_DIM})
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
