# src/palatium_ai/domain/ports/attachments.py

"""Port for attachment persistence; every read is explicitly user-scoped (060)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

# Imported from the submodule on purpose: the package ``__init__`` pulls in
# ``content`` → ``domain.ports.document_parser`` → ``domain.ports.__init__`` → here,
# so a package-level import would close a cycle at module load (000).
from palatium_ai.domain.attachments.models import Attachment


class AttachmentRepositoryPort(Protocol):
    """Persistence for the attachment aggregate.

    ``user_id`` is a required argument on every read and delete even though RLS
    also enforces isolation: RLS never replaces an explicit predicate (060).
    """

    async def create(self, attachment: Attachment) -> Attachment:
        """Insert a new attachment row."""
        ...

    async def save(self, attachment: Attachment) -> Attachment:
        """Persist the full aggregate after ``model_copy(update=...)``.

        Raises ``LookupError`` when no row matches the aggregate id for its owner:
        a silent no-op update would leave a state transition unpersisted.
        """
        ...

    async def get(self, attachment_id: UUID, *, user_id: str) -> Attachment | None:
        """Fetch one attachment owned by ``user_id``."""
        ...

    async def get_many(self, attachment_ids: Sequence[UUID], *, user_id: str) -> list[Attachment]:
        """Fetch several attachments at once, skipping ids not owned by ``user_id``."""
        ...

    async def list_for_thread(self, thread_id: str, *, user_id: str) -> list[Attachment]:
        """List attachments bound to one thread, newest first."""
        ...

    async def count_for_thread(self, thread_id: str, *, user_id: str) -> int:
        """Count attachments in a thread to enforce the per-turn intake limit."""
        ...

    async def delete(self, attachment_id: UUID, *, user_id: str) -> None:
        """Remove an attachment row owned by ``user_id``."""
        ...

    async def list_expired(
        self,
        cutoff: datetime,
        *,
        user_id: str,
        limit: int,
    ) -> list[Attachment]:
        """Oldest-first rows owned by ``user_id`` whose TTL elapsed before ``cutoff``.

        Deliberately user-scoped: ``attachments`` is under ``FORCE ROW LEVEL
        SECURITY``, so a cross-tenant maintenance query cannot be expressed with
        the app role at all (060). Retention is therefore enforced per owner.

        ``limit`` is mandatory and must be bounded by the caller's
        ``AttachmentLimits.retention_sweep_batch`` — an unbounded reclaim pass is
        one bad row away from an arbitrarily long delete loop (080).
        """
        ...
