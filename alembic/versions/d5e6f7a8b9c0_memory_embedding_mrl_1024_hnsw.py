"""Normalize memory.entries to 1024d MRL + HNSW if prior 4096 attempt applied.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-03 11:25:00.000000

Idempotent relative to c4d5e6f7a8b9@1024: clears vectors, ensures vector(1024)+HNSW.
Covers DBs that briefly landed on vector(4096) without ANN.
"""

from __future__ import annotations

from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"
TARGET_DIM = 1024


def upgrade() -> None:
    """Force memory.entries.embedding to 1024d with HNSW cosine index."""
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
    """No-op: cannot restore unknown prior width (384 vs 4096) safely."""
    # Intentionally empty — forward-only normalize.
