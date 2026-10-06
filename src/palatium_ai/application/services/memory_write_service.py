# src/palatium_ai/application/services/memory_write_service.py

"""Gated medium-term memory writes (060 Write / Wave M4).

EXCEPTION (020 interactive HITL): system paths (context compaction, sleep-time
extract helpers) call this without an interactive card. Every write still runs
secret scan + PII classify + audit. User-initiated ``save_memory`` remains
HITL-gated via ``MemorySaveService``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.pii import resolve_contains_pii
from palatium_ai.domain.memory.types import MemoryType

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

NamespaceKind = Literal["thread", "user", "org"]
_CANONICAL_TYPES: frozenset[str] = frozenset({"preference", "fact", "incident", "episode"})


class MemoryWriteService:
    """Single gated put path for system memory writes (scan → PII → put → audit)."""

    def __init__(self, memory_port: MemoryPort) -> None:
        self._memory = memory_port

    async def put_system(
        self,
        *,
        namespace_kind: NamespaceKind,
        scope_id: str,
        entry_key: str,
        text: str,
        source: str,
        thread_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
        kind: str = "fact",
        confidence: float = 1.0,
        scan_field: str = "memory_system_write",
    ) -> bool:
        """Persist one medium entry after gates; False on reject/empty (fail-closed on secrets)."""
        text_value = text.strip()
        if not text_value or not entry_key.strip() or not scope_id.strip():
            return False
        try:
            scan_text(text_value, field=scan_field)
        except SecretScanError:
            logger.warning(
                "memory_write.secret_blocked",
                source=source,
                thread_id=thread_id,
                entry_key=entry_key.strip()[:128],
            )
            return False

        namespace = _resolve_namespace(namespace_kind, scope_id.strip())
        memory_type = _canonical_type(kind)
        pii_flag = resolve_contains_pii(text=text_value, client_flag=False)
        value: dict[str, object] = {
            "text": text_value[:2000],
            "kind": kind.strip().lower() or "fact",
            "memory_type": memory_type,
            "confidence": max(0.0, min(1.0, confidence)),
            "source": source.strip()[:64] or "system",
            "thread_id": thread_id.strip(),
            "user_id": (user_id or "").strip(),
            "org_id": (org_id or "").strip(),
            "contains_pii": pii_flag,
        }
        await self._memory.put(namespace=namespace, key=entry_key.strip(), value=value)
        await _audit_write(
            thread_id=thread_id,
            entry_key=entry_key.strip(),
            source=source,
            contains_pii=pii_flag,
            namespace_kind=namespace_kind,
        )
        return True


def _resolve_namespace(kind: NamespaceKind, scope_id: str) -> tuple[str, ...]:
    if kind == "user":
        return user_namespace(scope_id)
    if kind == "org":
        return org_namespace(scope_id)
    return thread_namespace(scope_id)


def _canonical_type(kind: str) -> MemoryType:
    normalized = kind.strip().lower()
    if normalized in _CANONICAL_TYPES:
        return normalized  # type: ignore[return-value]  # membership не сужает str→MemoryType (017)
    return "fact"


async def _audit_write(
    *,
    thread_id: str,
    entry_key: str,
    source: str,
    contains_pii: bool,
    namespace_kind: str,
) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        await get_audit_logger().append_async(
            timestamp=timestamp,
            conversation_id=thread_id.strip() or "memory-write",
            event="memory_system_write",
            metadata={
                "entry_key": entry_key[:128],
                "source": source[:64],
                "namespace_kind": namespace_kind[:16],
                "contains_pii": "true" if contains_pii else "false",
            },
        )
    except Exception as exc:
        logger.warning("memory_write.audit_failed", error=str(exc))
