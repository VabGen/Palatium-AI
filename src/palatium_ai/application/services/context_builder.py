# src/palatium_ai/application/services/context_builder.py

"""JIT context assembly + compact (065) — keys declared by agents, built before run()."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from palatium_ai.core.context.tokens import record_context_tokens_used
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.memory.compact import CompactMethod, CompactRequest, CompactResult
from palatium_ai.domain.memory.namespaces import thread_namespace, user_namespace
from palatium_ai.domain.policies.compact import CompactPolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_write_service import MemoryWriteService
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort
    from palatium_ai.domain.ports.context_compact import DialogSummarizerPort
    from palatium_ai.domain.skills.port import SkillCatalogPort

logger = get_logger(__name__)

_PRESERVE_KEYS = ("goal", "plan", "last_results")
_PRESERVE_PREFIX = "compact_preserve:"
_COMPACT_SOURCE = "context_compact"
_DEFAULT_SKILL_CATALOG_MAX_CHARS = 4_000


class ContextSourcePort(Protocol):
    """Optional loaders for known JIT context keys."""

    async def load(self, key: str, *, thread_id: str, user_id: str | None, instruction: str) -> str: ...


class ContextBuilder:
    """Build ``dict[str, str]`` for AgentInput.context; compact dialog at 80% budget (065)."""

    def __init__(
        self,
        *,
        dialog_store: DialogTurnStore | None = None,
        memory_port: MemoryPort | None = None,
        memory_writer: MemoryWriteService | None = None,
        summarizer: DialogSummarizerPort | None = None,
        skill_catalog: SkillCatalogPort | None = None,
        skill_catalog_max_chars: int = _DEFAULT_SKILL_CATALOG_MAX_CHARS,
    ) -> None:
        self._dialog_store = dialog_store
        self._memory_port = memory_port
        self._memory_writer = memory_writer
        self._summarizer = summarizer
        self._skill_catalog = skill_catalog
        self._skill_catalog_max_chars = max(200, int(skill_catalog_max_chars))

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

    @traceable(name="context_builder.compact")
    async def compact(self, request: CompactRequest) -> CompactResult:
        """Summarize dialog when over threshold; persist goal/plan/last_results first (060/065)."""
        dialog = CompactPolicy.dedupe_exact_lines(request.dialog)
        goal = request.goal.strip()
        plan = request.plan.strip()
        last_results = request.last_results.strip()
        tokens_before = CompactPolicy.package_tokens(
            dialog=dialog,
            goal=goal,
            plan=plan,
            last_results=last_results,
        )
        limit = CompactPolicy.limit_tokens(model_tier=request.model_tier)

        if not CompactPolicy.needs_compact(tokens=tokens_before, model_tier=request.model_tier):
            return CompactResult(
                dialog=dialog,
                goal=goal,
                plan=plan,
                last_results=last_results,
                did_compact=False,
                method="none",
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                limit_tokens=limit,
            )

        persisted = await self._persist_preserved(
            thread_id=request.thread_id,
            user_id=request.user_id,
            goal=goal,
            plan=plan,
            last_results=last_results,
        )

        method: CompactMethod
        if self._summarizer is not None and dialog.strip():
            try:
                summarized = (await self._summarizer.summarize_dialog(dialog)).strip()
                if not summarized:
                    raise ValueError("empty summary")
                compact_dialog = f"[context_compacted method=llm tokens_before={tokens_before}]\n{summarized}"
                method = "llm"
            except Exception as exc:
                logger.warning(
                    "context_builder.summarizer_failed",
                    thread_id=request.thread_id,
                    error=str(exc)[:300],
                )
                compact_dialog = CompactPolicy.extractive_summary(dialog, tokens_before=tokens_before)
                method = "extractive"
        else:
            compact_dialog = CompactPolicy.extractive_summary(dialog, tokens_before=tokens_before)
            method = "extractive"

        tokens_after = CompactPolicy.package_tokens(
            dialog=compact_dialog,
            goal=goal,
            plan=plan,
            last_results=last_results,
        )
        logger.info(
            "context_compacted",
            thread_id=request.thread_id,
            method=method,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            limit_tokens=limit,
            persisted_keys=list(persisted),
        )
        record_context_tokens_used(agent_type="context_builder", tokens=tokens_after)

        return CompactResult(
            dialog=compact_dialog,
            goal=goal,
            plan=plan,
            last_results=last_results,
            did_compact=True,
            method=method,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            limit_tokens=limit,
            persisted_keys=persisted,
        )

    async def _persist_preserved(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        goal: str,
        plan: str,
        last_results: str,
    ) -> tuple[str, ...]:
        """Gated write of goal/plan/last_results before dialog compact (060.9 / M4)."""
        if self._memory_writer is None:
            logger.warning(
                "context_builder.compact_persist_skipped",
                thread_id=thread_id,
                reason="memory_writer_unavailable",
            )
            return ()

        values = {"goal": goal, "plan": plan, "last_results": last_results}
        persisted: list[str] = []
        for key, text in values.items():
            if not text:
                continue
            ok = await self._memory_writer.put_system(
                namespace_kind="thread",
                scope_id=thread_id,
                entry_key=f"{_PRESERVE_PREFIX}{key}",
                text=text,
                source=_COMPACT_SOURCE,
                thread_id=thread_id,
                user_id=user_id,
                kind="fact",
                confidence=1.0,
                scan_field="context_compact_preserve",
            )
            if ok:
                persisted.append(key)
            else:
                logger.warning(
                    "context_builder.compact_persist_rejected",
                    thread_id=thread_id,
                    key=key,
                )

        # Cross-session durability for goal when user is known (preference-like anchor).
        if goal and user_id and user_id.strip():
            await self._memory_writer.put_system(
                namespace_kind="user",
                scope_id=user_id.strip(),
                entry_key=f"{_PRESERVE_PREFIX}goal",
                text=goal,
                source=_COMPACT_SOURCE,
                thread_id=thread_id,
                user_id=user_id.strip(),
                kind="fact",
                confidence=1.0,
                scan_field="context_compact_preserve",
            )
        return tuple(persisted)

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
        if key in _PRESERVE_KEYS:
            return await self._load_preserved(key, thread_id=thread_id, user_id=user_id)
        if key == "long_term_memory" and self._memory_port is not None and user_id:
            hits = await self._memory_port.search(
                namespace=user_namespace(user_id),
                query=instruction,
                limit=5,
            )
            if not hits:
                return ""
            return "\n".join(str(h.get("text", h)) for h in hits)
        if key == "skill_catalog":
            # Unwired catalog → empty card (tests / minimal harness); production wires FilesystemSkillCatalog.
            if self._skill_catalog is None:
                return "(no procedural skills)"
            return self._skill_catalog.format_catalog(max_chars=self._skill_catalog_max_chars)
        msg = f"Unknown or unavailable context key: {key}"
        raise KeyError(msg)

    async def _load_preserved(self, key: str, *, thread_id: str, user_id: str | None) -> str:
        if self._memory_port is None:
            msg = f"Unknown or unavailable context key: {key}"
            raise KeyError(msg)
        item = await self._memory_port.get(
            namespace=thread_namespace(thread_id),
            key=f"{_PRESERVE_PREFIX}{key}",
        )
        if item is None and key == "goal" and user_id and user_id.strip():
            item = await self._memory_port.get(
                namespace=user_namespace(user_id.strip()),
                key=f"{_PRESERVE_PREFIX}goal",
            )
        if item is None:
            return ""
        return str(item.get("text", "")).strip()
