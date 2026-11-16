# src/palatium_ai/domain/policies/prompt_assembly.py

"""Prompt-cache tiers: stable → context → volatile (CMD2 / 065).

Prefix-cache stability: only the stable system block may carry ``cache_control``.
Memory hits and dialog live after that prefix so recall churn does not bust the
identity/rules cache (Anthropic / Hermes pattern; ADR-adjacent to 0008).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.llm.models import ChatMessage, DocumentPart, ImagePart

PromptTier = Literal["stable", "context", "volatile"]

_STABLE_HEADER = "## Stable (identity / rules)"
_AGENTS_HEADER = "## Project operating contract (AGENTS.md)"
_TOOLS_HEADER = "## Tool guidance"
_CONTEXT_HEADER = "## Context (session / retrieval)"
_MEMORY_HEADER = "### Memory hints"
_SKILLS_HEADER = "### Skill catalog (index)"
_META_HEADER = "### Thread meta"
_VOLATILE_HEADER = "## Volatile (turn-local)"
_DIALOG_HEADER = "### Dialog window"
_TS_HEADER = "### Timestamp"


class PromptAssemblyParts(BaseModel):
    """Inputs for one assembled LLM call (empty strings are omitted)."""

    model_config = {"frozen": True}

    system_identity: str = Field(min_length=1, max_length=200_000)
    project_agents_md: str = Field(default="", max_length=20_000)
    tool_guidance: str = Field(default="", max_length=50_000)
    thread_meta: str = Field(default="", max_length=8_000)
    skill_catalog: str = Field(default="", max_length=20_000)
    memory_block: str = Field(default="", max_length=16_000)
    dialog_block: str = Field(default="", max_length=100_000)
    timestamp: str = Field(default="", max_length=64)
    user_content: str = Field(min_length=1, max_length=500_000)
    image_parts: tuple[ImagePart, ...] = ()
    document_parts: tuple[DocumentPart, ...] = ()


class AssembledPrompt(BaseModel):
    """Ordered ChatMessages + tier labels for tests / metrics."""

    model_config = {"frozen": True}

    messages: tuple[ChatMessage, ...]
    tier_order: tuple[PromptTier, ...] = ()


class PromptAssemblyPolicy:
    """Pure assembler: stable → context → volatile; cache only on stable."""

    @staticmethod
    def assemble(parts: PromptAssemblyParts) -> AssembledPrompt:
        messages: list[ChatMessage] = []
        tiers: list[PromptTier] = []

        stable = _join_nonempty(
            _STABLE_HEADER,
            parts.system_identity.strip(),
            _section(_AGENTS_HEADER, parts.project_agents_md),
            _section(_TOOLS_HEADER, parts.tool_guidance),
        )
        messages.append(ChatMessage(role="system", content=stable, cache_control="ephemeral"))
        tiers.append("stable")

        context = _join_nonempty(
            _CONTEXT_HEADER,
            _section(_META_HEADER, parts.thread_meta),
            _section(_SKILLS_HEADER, parts.skill_catalog),
            _section(_MEMORY_HEADER, parts.memory_block),
        )
        if context.strip() and context.strip() != _CONTEXT_HEADER:
            messages.append(ChatMessage(role="system", content=context))
            tiers.append("context")

        volatile = _join_nonempty(
            _VOLATILE_HEADER,
            _section(_DIALOG_HEADER, parts.dialog_block),
            _section(_TS_HEADER, parts.timestamp),
        )
        if volatile.strip() and volatile.strip() != _VOLATILE_HEADER:
            messages.append(ChatMessage(role="system", content=volatile))
            tiers.append("volatile")

        messages.append(
            ChatMessage(
                role="user",
                content=parts.user_content,
                image_parts=parts.image_parts,
                document_parts=parts.document_parts,
            )
        )
        tiers.append("volatile")
        return AssembledPrompt(messages=tuple(messages), tier_order=tuple(tiers))

    @staticmethod
    def apply_cache_hints(messages: list[ChatMessage]) -> list[ChatMessage]:
        """Ensure the leading stable system message is cache-marked (Harness entry).

        If ``assemble()`` already set ``cache_control``, leave the list unchanged.
        Legacy callers (single system + user) get ephemeral on the first system only.
        Never mark context/volatile system messages that follow.
        """
        if not messages:
            return messages
        first = messages[0]
        if first.role != "system":
            return messages
        if first.cache_control is not None:
            return messages
        return [first.model_copy(update={"cache_control": "ephemeral"}), *messages[1:]]

    @staticmethod
    def assert_tier_invariants(assembled: AssembledPrompt) -> None:
        """Test helper: cache only on first message; order stable→context→volatile."""
        if not assembled.messages:
            msg = "assembled prompt is empty"
            raise AssertionError(msg)
        if assembled.messages[0].role != "system" or assembled.messages[0].cache_control != "ephemeral":
            msg = "stable system message must lead with cache_control=ephemeral"
            raise AssertionError(msg)
        for message in assembled.messages[1:]:
            if message.cache_control is not None:
                raise AssertionError("only the stable prefix may set cache_control")
        # Drop trailing user volatile label for order check of system tiers.
        system_tiers = [t for t, m in zip(assembled.tier_order, assembled.messages, strict=False) if m.role == "system"]
        allowed_prefixes = (
            ("stable",),
            ("stable", "context"),
            ("stable", "volatile"),
            ("stable", "context", "volatile"),
        )
        if tuple(system_tiers) not in allowed_prefixes:
            msg = f"unexpected system tier order: {system_tiers}"
            raise AssertionError(msg)


def _section(header: str, body: str) -> str:
    text = body.strip()
    if not text:
        return ""
    return f"{header}\n{text}"


def _join_nonempty(*chunks: str) -> str:
    return "\n\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())


__all__ = [
    "AssembledPrompt",
    "PromptAssemblyParts",
    "PromptAssemblyPolicy",
    "PromptTier",
]
