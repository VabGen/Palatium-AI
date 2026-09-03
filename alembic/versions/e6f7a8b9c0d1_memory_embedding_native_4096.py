"""Memory embeddings: native Qwen3-Embedding-8B 4096d (no MRL on corporate gateway).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-03 12:05:00.000000

Gateway returns 4096 and rejects `dimensions`. Float32 HNSW max is 2000 →
store vector(4096), drop HNSW, exact cosine search.
"""

from __future__ import annotations

from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
TARGET_DIM = 4096


def upgrade() -> None:
    """Widen to 4096d and remove float32 HNSW (incompatible with dim > 2000)."""
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
        ALTER COLUMN embedding TYPE vector({TARGET_DIM})
        """
    )


def downgrade() -> None:
    """Restore 1024d + HNSW (vectors cleared)."""
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
        ALTER COLUMN embedding TYPE vector(1024)
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
