"""Dynamic per-call LLM timeout formula (Phase 4)."""

from __future__ import annotations

_DEFAULT_BASE_SECONDS = 3.0
_FLOOR_SECONDS = 5.0
_CEILING_SECONDS = 90.0
_PROMPT_SECONDS_PER_TOKEN = 0.01
_OUTPUT_SECONDS_PER_TOKEN = 0.05


def compute_llm_timeout_seconds(
    *,
    prompt_tokens: int,
    max_tokens: int,
    base: float = _DEFAULT_BASE_SECONDS,
) -> float:
    """Base + prompt*0.01s + output*0.05s, пол 5s, потолок 90s."""
    prompt = max(0, int(prompt_tokens))
    output = max(0, int(max_tokens))
    raw = base + prompt * _PROMPT_SECONDS_PER_TOKEN + output * _OUTPUT_SECONDS_PER_TOKEN
    return min(max(raw, _FLOOR_SECONDS), _CEILING_SECONDS)
