# src/palatium_ai/application/services/intent_turn_helpers.py

"""Shared helpers for intent graph runs and HITL resume (no I/O orchestration)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.redact import redact_text
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentRevision, document_content_hash, document_revision
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.extract_admission import ExtractAdmissionPolicy

if TYPE_CHECKING:
    from palatium_ai.application.orchestration.state import AgentGraphState
    from palatium_ai.application.services.memory_extract import MemoryExtractService

logger = get_logger(__name__)

#: Payload schema tag for persisted assistant turns. History readers must keep treating
#: unknown tags as "no structured document" instead of guessing a shape.
ASSISTANT_TURN_SCHEMA = "assistant_turn_v1"

PENDING_ATTACHMENT_IDS_KEY = "pending_attachment_ids"


def serialize_pending_attachment_ids(attachment_ids: list[UUID] | tuple[UUID, ...]) -> str:
    """Encode UUIDs for session.context (server control plane)."""
    return ",".join(str(item) for item in attachment_ids)


def parse_pending_attachment_ids(raw: object) -> list[UUID]:
    """Decode comma-separated UUIDs from session.context; skip invalid tokens."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    parsed: list[UUID] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            parsed.append(UUID(token))
        except ValueError:
            continue
    return parsed


async def write_audit(*, conversation_id: str, event: str, metadata: dict[str, str]) -> None:
    """Записывает событие в аудит."""
    logger = get_audit_logger()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await logger.append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )


def resolved_turn_kind(final_state: AgentGraphState) -> str:
    """Task kind of the finished turn (routing intent wins over raw classification)."""
    routing_intent = final_state.get("routing_intent")
    if routing_intent is not None:
        return str(routing_intent.task_kind)
    classification = final_state.get("classification")
    if isinstance(classification, IntentTaskResult) and classification.output is not None:
        return str(classification.output.task_kind)
    return "clarification_needed"


async def enqueue_turn_extract(
    consolidation: MemoryExtractService | None,
    final_state: AgentGraphState,
    *,
    thread_id: str,
    task_id: str,
    user_id: str | None,
    org_id: str | None,
) -> str:
    """Enqueue sleep-time extract only when the turn holds something recallable (060).

    One job = one MemoryKeeper LLM call over the last dialog window, so admission is
    a domain decision (``ExtractAdmissionPolicy``), not ``status == "success"`` —
    otherwise every "спасибо" pays for a frontier-tier extraction (080).
    Returns the decision reason for callers that log/assert it.
    """
    from palatium_ai.application.orchestration import selectors as orch_selectors

    if consolidation is None:
        return "disabled"
    task_kind = resolved_turn_kind(final_state)
    strategy = orch_selectors.selected_strategy(final_state)
    admission = ExtractAdmissionPolicy.decide(task_kind=task_kind, strategy=strategy)
    if admission.admit:
        await consolidation.enqueue(
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            org_id=org_id,
        )
        return admission.reason
    agent_metrics.record_memory_extract_skipped(reason=admission.reason)
    logger.info(
        "memory_extract.skipped",
        reason=admission.reason,
        task_kind=task_kind,
        strategy=strategy,
        thread_id=thread_id,
        task_id=task_id,
    )
    return admission.reason


def tenant_budget_key(*, user_id: str | None, org_id: str | None, thread_id: str) -> str:
    """Stable tenant key for daily cost accounting."""
    if user_id and user_id.strip():
        return user_id.strip()
    if org_id and org_id.strip():
        return f"org:{org_id.strip()}"
    return f"thread:{thread_id}"


def derive_session_title(text: str) -> str:
    """Build a stable human-readable title from the first user utterance."""
    normalized = " ".join(text.split())
    return normalized[:80] if normalized else "Untitled session"


def response_preview(result: FormatterTaskResult) -> str:
    """Return a short preview of the latest formatted response for session context."""
    if result.output is None:
        return result.error or ""
    return result.output.preview_text(200)


def assistant_turn_content(result: FormatterTaskResult) -> str:
    """Persist flattened assistant body for Contextualizer (not title-only preview)."""
    if result.output is None:
        return result.error or "(empty assistant response)"
    return result.output.plain_text(4000)


def _previous_assistant_document(window: DialogTurnWindow | None) -> ContentDocument | None:
    """Last persisted answer of the thread, if it is readable as a document.

    A malformed or legacy turn is skipped, not raised: an unreadable old answer is a
    missing diff base, never a failed turn (035).
    """
    from pydantic import ValidationError

    if window is None:
        return None
    for turn in reversed(window.turns):
        if turn.role != "assistant" or not isinstance(turn.payload, dict):
            continue
        if turn.payload.get("schema") != ASSISTANT_TURN_SCHEMA:
            continue
        raw = turn.payload.get("document")
        if raw is None:
            continue
        try:
            return ContentDocument.model_validate(raw)
        except ValidationError:
            continue
    return None


def assistant_revision(
    result: FormatterTaskResult,
    window: DialogTurnWindow | None,
    *,
    revision_requested: bool,
) -> DocumentRevision | None:
    """Server-side diff against the previous answer — ids are hashes, never model output.

    ``revision_requested`` comes from ``RevisionPolicy`` (re-answer after rejection, or a
    transform of the prior answer). Identical output is not a revision: a re-render must
    not claim a diff of nothing.
    """
    if not revision_requested or result.output is None:
        return None
    previous = _previous_assistant_document(window)
    if previous is None:
        return None
    if document_content_hash(previous) == document_content_hash(result.output):
        return None
    return document_revision(previous, result.output)


def turn_revision(
    result: FormatterTaskResult,
    final_state: AgentGraphState,
) -> DocumentRevision | None:
    """Diff of this turn against the previous answer — the only entry point for callers.

    The *decision* (``RevisionPolicy``) and the *computation* (``document_revision``)
    each live in one place; callers must not re-assemble the axes themselves, otherwise
    the persisted payload and the live response could disagree about what a revision is.
    """
    from palatium_ai.application.orchestration import selectors as orch_selectors
    from palatium_ai.domain.policies.revision import RevisionPolicy

    return assistant_revision(
        result,
        final_state.get("dialog_window"),
        revision_requested=RevisionPolicy.continues_prior_document(
            revision_feedback=orch_selectors.resolved_revision_feedback(final_state),
            transformation=orch_selectors.resolved_transformation(final_state),
        ),
    )


@dataclass(frozen=True, slots=True)
class FinalizedTurn:
    """One persisted assistant turn: the agent result and the server-computed diff.

    ``revision`` cannot live on ``FormatterTaskResult`` (030: the agent returns its own
    output, not store facts), yet every caller of a finalize step needs both — the SSE
    frame, the HITL resume envelope, the persisted payload. Returning the pair keeps a
    single computation and stops call sites from re-deriving "is this a revision?".
    """

    result: FormatterTaskResult
    revision: DocumentRevision | None = None


def assistant_turn_payload(
    result: FormatterTaskResult,
    *,
    revision: DocumentRevision | None = None,
) -> dict[str, object] | None:
    """Persist document + HITL card ids/meta for hydrate — never capability tokens."""
    from palatium_ai.domain.hitl.choice_resume import hitl_card_public_dump

    if result.output is None and not result.hitl_cards:
        return None
    payload: dict[str, object] = {
        "schema": ASSISTANT_TURN_SCHEMA,
        "document": result.output.model_dump(mode="json") if result.output is not None else None,
        "hitl_cards": [hitl_card_public_dump(card) for card in result.hitl_cards],
    }
    if revision is not None:
        payload["revision"] = revision.model_dump(mode="json")
    return payload


def stream_result_frame(
    result: FormatterTaskResult,
    *,
    task_id: str,
    thread_id: str,
    revision: DocumentRevision | None = None,
) -> dict[str, object]:
    """Final SSE frame of a turn: the agent result plus the server-computed diff.

    ``revision`` rides here, not inside ``FormatterTaskResult``: the diff is produced at
    the persist boundary, not by the Formatter, and must not become part of the agent
    contract (030). Key is absent when the answer is not a revision, matching the
    persisted turn payload — one shape for live and hydrated turns.
    """
    frame: dict[str, object] = {
        "event": "result",
        "task_id": task_id,
        "thread_id": thread_id,
        "result": result.model_dump(mode="json"),
    }
    if revision is not None:
        frame["revision"] = revision.model_dump(mode="json")
    return frame


def snapshot_awaits_resume(snapshot: object) -> bool:
    """Return whether checkpointer awaits Command(resume=...) for a tool interrupt."""
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if interrupts:
        return True
    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        task_interrupts = getattr(task, "interrupts", None) or ()
        if task_interrupts:
            return True
    values = getattr(snapshot, "values", None)
    return bool(isinstance(values, dict) and values.get("__interrupt__"))


def extract_interrupt(state: object) -> dict[str, object] | None:
    """Read LangGraph `__interrupt__` payload when a node called interrupt()."""
    if not isinstance(state, dict):
        return None
    raw = state.get("__interrupt__")
    if not raw:
        return None
    items = raw if isinstance(raw, (list, tuple)) else (raw,)
    first = items[0] if items else None
    value = getattr(first, "value", first)
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return None


def argument_preview(arguments: object) -> str:
    """Возвращает краткое представление аргументов для HITL (секреты redacted)."""
    if not isinstance(arguments, dict):
        return ""
    parts: list[str] = []
    for key, value in list(arguments.items())[:8]:
        display = redact_text(value) if isinstance(value, str) else repr(value)
        parts.append(f"{key}={display}")
    preview = ", ".join(parts)
    return redact_text(preview)
