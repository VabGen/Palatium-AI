"""Reservation column for medium→graph promote (060 / M5 audit F6).

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-10-21 13:20:00.000000

``list_promotion_candidates`` + ``upsert_fact`` is a read-then-write pair, so two
promoters (scheduled job and an operator CLI) could both see ``promoted_at IS NULL``
and write the same graph version — observed on the live stand as two active
``:MemoryFact`` nodes with one ``node_id``. ``promote_claimed_at`` turns the read into
a compare-and-set inside one UPDATE; the lease makes a crashed promoter recoverable.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "k1f2a3b4c5d6"
down_revision = "j0e1f2a3b4c5"
branch_labels = None
depends_on = None

MEMORY_SCHEMA = "memory"


def upgrade() -> None:
    op.add_column(
        "entries",
        sa.Column("promote_claimed_at", sa.DateTime(timezone=True), nullable=True),
        schema=MEMORY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("entries", "promote_claimed_at", schema=MEMORY_SCHEMA)
