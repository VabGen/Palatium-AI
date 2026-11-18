# src/palatium_ai/application/agents/memory_keeper/parsing.py

"""Decode MemoryKeeper AgentInput and parse LLM output."""

from __future__ import annotations

import json
import math

from typing import cast

from palatium_ai.application.agents.memory_keeper.config import MEMORY_KINDS, MEMORY_SCOPES
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.agents.memory_keeper import (
    MemoryFactCandidate,
    MemoryKeeperInput,
    MemoryKeeperOutput,
    MemoryKind,
    MemoryScope,
)
from palatium_ai.domain.llm.json_codec import loads_llm_json


def decode_memory_keeper_input(input_context: dict[str, str]) -> MemoryKeeperInput:
    existing_raw = json.loads(input_context.get("existing_memory_texts_json", "[]"))
    existing = tuple(str(item) for item in existing_raw)
    return MemoryKeeperInput(
        task_id=input_context["_task_id"],
        thread_id=input_context["thread_id"],
        transcript_excerpt=input_context["transcript_excerpt"],
        existing_memory_texts=existing,
    )


def parse_memory_keeper_output(raw: str) -> MemoryKeeperOutput:
    """Parse LLM JSON with per-fact sanitization."""
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
        kind_raw = str(item.get("kind", "fact")).strip().lower()
        # Soft-migrate pre-060 extract labels onto MemoryType (060). ``entity`` is a
        # durable fact about an org/person — its sharing tier belongs to ``scope``.
        if kind_raw == "entity":
            kind_raw = "fact"
        elif kind_raw == "summary":
            kind_raw = "episode"
        kind = cast("MemoryKind", kind_raw if kind_raw in MEMORY_KINDS else "fact")
        scope_raw = item.get("scope")
        scope_key = scope_raw.strip().lower() if isinstance(scope_raw, str) else ""
        scope = cast("MemoryScope", scope_key) if scope_key in MEMORY_SCOPES else None
        confidence = _clamp_confidence(coerce_float(item.get("confidence", 0.0)))
        key_hint_raw = item.get("key_hint")
        key_hint = str(key_hint_raw)[:128] if isinstance(key_hint_raw, str) and key_hint_raw.strip() else None
        facts.append(
            MemoryFactCandidate(
                text=text[:2000],
                kind=kind,
                scope=scope,
                confidence=confidence,
                key_hint=key_hint,
            )
        )
    return MemoryKeeperOutput(
        facts=tuple(facts),
        reasoning=str(payload.get("reasoning", ""))[:1000],
    )


def _clamp_confidence(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)
