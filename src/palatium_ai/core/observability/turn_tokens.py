# src/palatium_ai/core/observability/turn_tokens.py

"""Per-turn LLM token collector (ContextVar, complements hop_timings)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(slots=True)
class AgentTokenUsage:
    """Tokens attributed to one agent LLM call."""

    agent: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float = 0.0


@dataclass
class TurnTokenCollector:
    """Mutable token totals for the active turn."""

    usages: list[AgentTokenUsage] = field(default_factory=list)

    def record(
        self,
        *,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        """Append one LLM usage sample for this turn."""
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return
        self.usages.append(
            AgentTokenUsage(
                agent=agent,
                model=model,
                prompt_tokens=max(0, prompt_tokens),
                completion_tokens=max(0, completion_tokens),
                cost_usd=max(0.0, cost_usd),
            )
        )

    def as_log_fields(self) -> dict[str, object]:
        """Compact token summary for structlog."""
        prompt_total = sum(item.prompt_tokens for item in self.usages)
        completion_total = sum(item.completion_tokens for item in self.usages)
        cost_total = sum(item.cost_usd for item in self.usages)
        by_agent: dict[str, int] = {}
        for item in self.usages:
            by_agent[item.agent] = by_agent.get(item.agent, 0) + item.prompt_tokens + item.completion_tokens
        return {
            "token_prompt_total": prompt_total,
            "token_completion_total": completion_total,
            "token_total": prompt_total + completion_total,
            "token_by_agent": by_agent,
            "llm_calls": len(self.usages),
            "cost_usd_total": round(cost_total, 6),
        }


_current: ContextVar[TurnTokenCollector | None] = ContextVar("turn_tokens", default=None)


def get_turn_token_collector() -> TurnTokenCollector | None:
    """Return collector for the active turn, if any."""
    return _current.get()


@contextmanager
def turn_token_usage() -> Iterator[TurnTokenCollector]:
    """Bind a fresh token collector for one IntentService turn."""
    collector = TurnTokenCollector()
    token: Token[TurnTokenCollector | None] = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)
