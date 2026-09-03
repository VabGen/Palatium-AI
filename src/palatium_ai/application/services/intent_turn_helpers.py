# src/palatium_ai/application/services/intent_turn_helpers.py

"""Shared helpers for intent graph runs and HITL resume (no I/O orchestration)."""

from __future__ import annotations

from datetime import UTC, datetime

from palatium_ai.core.logging.redact import redact_text
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.agents.formatter import FormatterTaskResult


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


def assistant_turn_payload(result: FormatterTaskResult) -> dict[str, object] | None:
    """Persist document + HITL card ids/meta for hydrate — never capability tokens."""
    from palatium_ai.domain.hitl.choice_resume import hitl_card_public_dump

    if result.output is None and not result.hitl_cards:
        return None
    return {
        "schema": "assistant_turn_v1",
        "document": result.output.model_dump(mode="json") if result.output is not None else None,
        "hitl_cards": [hitl_card_public_dump(card) for card in result.hitl_cards],
    }


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
