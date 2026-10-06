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

    async def create_under_upload_quota(
        self,
        attachment: Attachment,
        *,
        limit: int,
        pending_cutoff: datetime,
    ) -> Attachment | None:
        """Insert the row only while the thread's in-flight uploads stay under ``limit``.

        Returns the stored aggregate, or ``None`` when the quota is already exhausted;
        the caller turns ``None`` into a typed refusal.

        The count and the insert must happen in **one** transaction guarded by a
        per-thread lock. A separate count read followed by ``create`` is a TOCTOU
        race under READ COMMITTED: two concurrent ``init`` calls both observe
        ``limit - 1`` and both insert, so a five-file cap admits six rows (020).

        ``pending_cutoff`` is what "in-flight" means: only ``pending`` rows created
        after it occupy a slot. Uploads whose presigned ticket already expired can
        never complete, so they must release their slot immediately rather than
        block the thread for the row's whole retention TTL (080).
        """
        ...

    async def delete(self, attachment_id: UUID, *, user_id: str) -> None:
        """Remove an attachment row owned by ``user_id``."""
        ...

    async def list_reclaimable(
        self,
        cutoff: datetime,
        *,
        pending_before: datetime,
        user_id: str,
        limit: int,
    ) -> list[Attachment]:
        """Oldest-first rows owned by ``user_id`` that retention may reclaim.

        A row qualifies when **either** its TTL elapsed before ``cutoff`` **or** it
        is a ``pending`` upload created before ``pending_before`` and therefore can
        never receive its bytes — an abandoned intake would otherwise sit in the
        table for the full retention TTL, invisible to the sweep.

        Deliberately user-scoped: ``attachments`` is under ``FORCE ROW LEVEL
        SECURITY``, so a cross-tenant maintenance query cannot be expressed with
        the app role at all (060). Retention is therefore enforced per owner.

        ``limit`` is mandatory and must be bounded by the caller's
        ``AttachmentLimits.retention_sweep_batch`` — an unbounded reclaim pass is
        one bad row away from an arbitrarily long delete loop (080).
        """
        ...
