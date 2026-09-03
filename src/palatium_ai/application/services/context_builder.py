# src/palatium_ai/application/services/context_builder.py

"""JIT context assembly (065) — keys declared by agents, built before run()."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort


class ContextSourcePort(Protocol):
    """Optional loaders for known JIT context keys."""

    async def load(self, key: str, *, thread_id: str, user_id: str | None, instruction: str) -> str: ...


class ContextBuilder:
    """Build ``dict[str, str]`` for AgentInput.context (065)."""

    def __init__(
        self,
        *,
        dialog_store: DialogTurnStore | None = None,
        memory_port: MemoryPort | None = None,
    ) -> None:
        self._dialog_store = dialog_store
        self._memory_port = memory_port

    async def build(
        self,
        keys: list[str],
        *,
        thread_id: str,
        user_id: str | None = None,
        instruction: str = "",
    ) -> dict[str, str]:
        """Load only requested keys; missing loader → KeyError (no silent skip)."""
        if not keys:
            return {}
        context: dict[str, str] = {}
        for key in keys:
            context[key] = await self._load_key(
                key,
                thread_id=thread_id,
                user_id=user_id,
                instruction=instruction,
            )
        return context

    async def _load_key(
        self,
        key: str,
        *,
        thread_id: str,
        user_id: str | None,
        instruction: str,
    ) -> str:
        if key == "history" and self._dialog_store is not None:
            window = await self._dialog_store.list_recent_turns(thread_id=thread_id, limit=12)
            lines = [f"{t.role}: {t.content}" for t in window.turns]
            return "\n".join(lines)
        if key == "long_term_memory" and self._memory_port is not None and user_id:
            hits = await self._memory_port.search(
                namespace=("user", user_id),
                query=instruction,
                limit=5,
            )
            if not hits:
                return ""
            return "\n".join(str(h.get("text", h)) for h in hits)
        msg = f"Unknown or unavailable context key: {key}"
        raise KeyError(msg)
