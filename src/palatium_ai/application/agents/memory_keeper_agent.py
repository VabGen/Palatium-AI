# src/palatium_ai/application/agents/memory_keeper_agent.py

"""MemoryKeeper — sleep-time ADD-only consolidation (Letta-style, off hot path)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from palatium_ai.application.agents.base import BaseAgent
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.memory_keeper import (
    MemoryFactCandidate,
    MemoryKeeperInput,
    MemoryKeeperOutput,
    MemoryKeeperTaskResult,
    MemoryKind,
)
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.contracts import AgentContext

MEMORY_KEEPER_CONFIG = AgentConfig(
    name="memory_keeper",
    role="memory_keeper",
    model_tier="frontier",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=120,
    max_retries=2,
    confidence_threshold=0.7,
)

_SYSTEM_PROMPT = """You extract durable memories from a chat transcript (sleep-time).
ADD-only: propose NEW facts/preferences/entities worth remembering later.
Do NOT invent facts. Do NOT propose updates/deletes of existing memories.
Skip ephemeral chit-chat, one-off formatting requests, and secrets (tokens, passwords).

Return ONLY JSON:
{
  "facts": [
    {"text": "...", "kind": "fact"|"preference"|"entity"|"summary", "confidence": 0.0-1.0, "key_hint": "optional-slug"}
  ],
  "reasoning": "brief"
}

If nothing durable — {"facts": [], "reasoning": "..."}.
Max 5 facts. Prefer high confidence (>=0.7).
"""

_KINDS = frozenset({"fact", "preference", "entity", "summary"})


class MemoryKeeperAgent(BaseAgent):
    """Consolidates transcript into ADD-only memory candidates."""

    config = MEMORY_KEEPER_CONFIG

    @traceable(name="memory_keeper.execute")
    async def execute(
        self,
        task_input: MemoryKeeperInput,
        context: AgentContext,
    ) -> MemoryKeeperTaskResult:
        """Extract ADD-only memory candidates; never writes to store itself."""
        _ = context
        agent_metrics.record_node_execution("memory_keeper", "memory_keeper_execute")

        existing = "\n".join(f"- {text}" for text in task_input.existing_memory_texts[:20]) or "(none)"
        user_prompt = (
            f"thread_id={task_input.thread_id}\n"
            f"existing_memories:\n{existing}\n\n"
            f"transcript:\n{task_input.transcript_excerpt}"
        )
        completion = await self._call_llm(
            [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_prompt),
            ],
            response_format="json_object",
        )
        output = _parse_output(completion.content)
        high = tuple(f for f in output.facts if f.confidence >= self.config.confidence_threshold)
        confidence = min((f.confidence for f in high), default=1.0) if high else 1.0
        status: Literal["success", "failure", "partial"] = "success" if high or not output.facts else "partial"
        return MemoryKeeperTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=confidence,
            requires_review=False,
            output=MemoryKeeperOutput(facts=high, reasoning=output.reasoning),
        )


def _parse_output(raw: str) -> MemoryKeeperOutput:
    payload = loads_llm_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("MemoryKeeper JSON must be an object")
    facts_raw = payload.get("facts", [])
    if not isinstance(facts_raw, list):
        raise ValueError("facts must be a list")
    facts: list[MemoryFactCandidate] = []
    for item in facts_raw[:5]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        kind_raw = str(item.get("kind", "fact"))
        kind = cast("MemoryKind", kind_raw if kind_raw in _KINDS else "fact")
        confidence = max(0.0, min(1.0, coerce_float(item.get("confidence", 0.0))))
        key_hint = item.get("key_hint")
        facts.append(
            MemoryFactCandidate(
                text=text[:2000],
                kind=kind,
                confidence=confidence,
                key_hint=str(key_hint)[:128] if key_hint else None,
            )
        )
    return MemoryKeeperOutput(
        facts=tuple(facts),
        reasoning=str(payload.get("reasoning", ""))[:1000],
    )
