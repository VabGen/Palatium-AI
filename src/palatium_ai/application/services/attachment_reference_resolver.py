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
from palatium_ai.domain.attachments.content import AttachmentContent
from palatium_ai.domain.policies.file_reference import (
    FileRefCandidate,
    FileReferencePolicy,
    FileReferenceResolution,
)
from palatium_ai.domain.ports.blob_store import BlobNotFoundError

if TYPE_CHECKING:
    from palatium_ai.domain.attachments.models import Attachment
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort
    from palatium_ai.domain.ports.blob_store import BlobStorePort

logger = get_logger(__name__)

#: Row states whose body may be read / lazily parsed (mirrors AttachmentReadService).
_USABLE = frozenset({"ready", "indexed"})
#: Cap on derived/OCR preview loaded for topical matching (same as policy).
_SEARCH_PREVIEW_CHARS = 4_000


class AttachmentReferenceResolver:
    """Owner + thread scoped reference resolution for the re-read path."""

    def __init__(
        self,
        *,
        repository: AttachmentRepositoryPort,
        blob_store: BlobStorePort | None = None,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store

    @traceable(name="attachment_reference.resolve")
    async def resolve(
        self,
        *,
        user_id: str,
        thread_id: str,
        hint_text: str = "",
        filename: str = "",
        all_requested: bool = False,
    ) -> FileReferenceResolution:
        """Return a typed resolution; refusals carry user-safe candidate names.

        ``all_requested`` is the explicit-plurality case («сравни оба файла»): Intent
        already decided the ask spans the whole set, so the resolver returns every
        readable file instead of refusing with ``several_thread_files``. Identity is
        still code-owned — the model only said "all of them" (055).
        """
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
        resolution = (
            FileReferencePolicy.resolve_all(candidates)
            if all_requested
            else FileReferencePolicy.resolve(candidates, hint_text=hint_text, filename=filename)
        )
        # Name miss with several files: enrich from MinIO derived/OCR text and retry
        # so «файл про иван-чай» can uniquely resolve ht_1-5.webp (055 / registry SoT).
        if (
            not all_requested
            and not (filename or "").strip()
            and resolution.status == "ambiguous"
            and resolution.reason == "several_thread_files"
            and (hint_text or "").strip()
            and self._blob_store is not None
        ):
            enriched = await self._candidates_with_search_text(attachments)
            if any(item.search_text for item in enriched):
                resolution = FileReferencePolicy.resolve(enriched, hint_text=hint_text)
        if not candidates and attachments:
            resolution = resolution.model_copy(update={"reason": "thread_files_not_readable"})
        if resolution.status != "resolved":
            # This resolver runs on *every* turn (the paraphrased-file-name probe), so a
            # thread with no files yet is the ordinary case, not an incident: logging it
            # at WARNING put a "failure" line on every greeting and buried the genuine
            # refusals. Only a mismatch against existing rows is actionable (040, 055).
            empty_thread = resolution.status == "no_candidates" and resolution.reason == "thread_has_no_files" and not attachments
            log_failure = logger.debug if empty_thread else logger.warning
            log_failure(
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
            resolved_count=len(resolution.attachment_ids),
            all_requested=all_requested,
        )
        return resolution

    async def thread_has_readable_files(self, *, user_id: str, thread_id: str) -> bool:
        """True when the attachment registry holds at least one readable row.

        Dialog-turn payloads age out of the window; the registry is the SoT for
        ``has_thread_files`` on Intent (055) — same source the UI «Все файлы» uses.
        """
        scoped_thread = (thread_id or "").strip()
        owner = (user_id or "").strip()
        if not scoped_thread or not owner:
            return False
        attachments = await self._repository.list_for_thread(scoped_thread, user_id=owner)
        return any(item.status in _USABLE for item in attachments)

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

    async def _candidates_with_search_text(
        self,
        attachments: list[Attachment],
    ) -> tuple[FileRefCandidate, ...]:
        """Load truncated derived/OCR previews for usable rows (MinIO / blob)."""
        out: list[FileRefCandidate] = []
        for item in attachments:
            if item.status not in _USABLE:
                continue
            preview = await self._load_search_preview(item)
            out.append(
                FileRefCandidate(
                    attachment_id=item.id,
                    filename=item.filename,
                    search_text=preview,
                )
            )
        return tuple(out)

    async def _load_search_preview(self, attachment: Attachment) -> str:
        if self._blob_store is None or not attachment.derived_text_key:
            return ""
        try:
            raw = await self._blob_store.read_bytes(attachment.derived_text_key)
        except BlobNotFoundError:
            return ""
        except Exception:  # noqa: BLE001  # preview is optimisations-only; never fail the turn (030.8)
            logger.warning(
                "attachment_reference.search_preview_failed",
                attachment_id=str(attachment.id),
                reason="blob_read_error",
            )
            return ""
        try:
            content = AttachmentContent.model_validate_json(raw)
        except Exception:  # noqa: BLE001  # corrupt derived JSON → skip content match
            return ""
        return (content.safe_text or "")[:_SEARCH_PREVIEW_CHARS]


def _usable_candidates(attachments: list[Attachment]) -> tuple[FileRefCandidate, ...]:
    """Rows whose body may be read, mapped to the pure-policy candidate type."""
    return tuple(
        FileRefCandidate(attachment_id=item.id, filename=item.filename) for item in attachments if item.status in _USABLE
    )


def _normalized(filename: str) -> str:
    return " ".join((filename or "").split()).casefold()


__all__ = ["AttachmentReferenceResolver"]
