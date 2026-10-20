# src/palatium_ai/application/services/attachment_reference_resolver.py

"""Resolve a thread-bound file reference before ``platform.read_attachment`` (055, 070).

The worker path must turn «этот файл / тот документ» into an ``attachment_id`` without
asking the model to invent one. The repository is the only registry of what the thread
holds (``list_for_thread``, owner-scoped + ``FORCE RLS``), and the choice itself is a
pure policy — no LLM judgement about *which* file the user meant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.policies.file_reference import (
    FileRefCandidate,
    FileReferencePolicy,
    FileReferenceResolution,
)

if TYPE_CHECKING:
    from palatium_ai.domain.attachments.models import Attachment
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort

logger = get_logger(__name__)

#: Row states whose body may be read / lazily parsed (mirrors AttachmentReadService).
_USABLE = frozenset({"ready", "indexed"})


class AttachmentReferenceResolver:
    """Owner + thread scoped reference resolution for the re-read path."""

    def __init__(self, *, repository: AttachmentRepositoryPort) -> None:
        self._repository = repository

    @traceable(name="attachment_reference.resolve")
    async def resolve(
        self,
        *,
        user_id: str,
        thread_id: str,
        hint_text: str = "",
        filename: str = "",
    ) -> FileReferenceResolution:
        """Return a typed resolution; refusals carry user-safe candidate names."""
        scoped_thread = (thread_id or "").strip()
        if not scoped_thread:
            # The read path is thread-scoped by contract (P0-A): without an id no
            # row can be selected. Log the missing binding instead of letting an
            # empty result read as "this dialog has no files" (055, 020).
            logger.warning(
                "attachment_reference.resolve_failed",
                thread_id="",
                reason="thread_id_missing",
                user_scoped=bool((user_id or "").strip()),
            )
            return FileReferenceResolution(status="no_candidates", reason="thread_has_no_files")
        attachments = await self._repository.list_for_thread(scoped_thread, user_id=user_id)
        candidates = _usable_candidates(attachments)
        resolution = FileReferencePolicy.resolve(candidates, hint_text=hint_text, filename=filename)
        if not candidates and attachments:
            resolution = resolution.model_copy(update={"reason": "thread_files_not_readable"})
        if resolution.status != "resolved":
            logger.warning(
                "attachment_reference.resolve_failed",
                thread_id=scoped_thread,
                status=resolution.status,
                reason=resolution.reason,
                candidate_count=len(candidates),
                # Counts only: file names are user content and stay out of logs (020).
                thread_file_count=len(attachments),
            )
        agent_metrics.record_attachment_read(
            kind=f"reference_{resolution.status}",
            ocr_applied=False,
            ocr_engine="none",
            ocr_cached=False,
        )
        logger.info(
            "attachment_reference.resolve",
            thread_id=scoped_thread,
            status=resolution.status,
            reason=resolution.reason,
            candidate_count=len(candidates),
            thread_file_count=len(attachments),
        )
        return resolution

    async def resolve_explicit(
        self,
        *,
        user_id: str,
        thread_id: str,
        filename: str,
    ) -> FileReferenceResolution:
        """Resolve a pick from the file-choice card (explicit user selection).

        The card offers one option per *name*; the thread may hold several rows with
        the same name (re-uploads). Those rows are indistinguishable to the user, so
        the newest usable row wins — the repository lists newest first. Anything else
        is the ordinary fail-closed resolution (020).
        """
        attachments = await self._repository.list_for_thread((thread_id or "").strip(), user_id=user_id)
        candidates = _usable_candidates(attachments)
        resolution = FileReferencePolicy.resolve(candidates, filename=filename)
        if resolution.status == "ambiguous" and resolution.reason == "explicit_filename_ambiguous":
            wanted = _normalized(filename)
            newest = next((item for item in candidates if _normalized(item.filename) == wanted), None)
            if newest is not None:
                resolution = FileReferenceResolution(
                    status="resolved",
                    attachment_id=newest.attachment_id,
                    filename=newest.filename,
                    candidates=(newest.filename,),
                    reason="card_choice_duplicate_name_newest",
                )
        if resolution.status != "resolved":
            logger.warning(
                "attachment_reference.resolve_explicit_failed",
                thread_id=(thread_id or "").strip(),
                status=resolution.status,
                reason=resolution.reason,
                candidate_count=len(candidates),
                thread_file_count=len(attachments),
            )
        logger.info(
            "attachment_reference.resolve_explicit",
            thread_id=(thread_id or "").strip(),
            status=resolution.status,
            reason=resolution.reason,
            candidate_count=len(candidates),
            thread_file_count=len(attachments),
        )
        return resolution


def _usable_candidates(attachments: list[Attachment]) -> tuple[FileRefCandidate, ...]:
    """Rows whose body may be read, mapped to the pure-policy candidate type."""
    return tuple(
        FileRefCandidate(attachment_id=item.id, filename=item.filename) for item in attachments if item.status in _USABLE
    )


def _normalized(filename: str) -> str:
    return " ".join((filename or "").split()).casefold()


__all__ = ["AttachmentReferenceResolver"]
