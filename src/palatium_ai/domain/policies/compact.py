# src/palatium_ai/domain/policies/compact.py

"""When and how to compact dialog context (065) — threshold from model_registry."""

from __future__ import annotations

from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.core.types.model_registry import context_limit_tokens

# 065: compact at 80% of tier context limit (not a magic number in call sites).
COMPACT_THRESHOLD_RATIO = 0.8
_EXTRACTIVE_HEAD_CHARS = 1_500
_EXTRACTIVE_TAIL_CHARS = 4_000


class CompactPolicy:
    """Pure policy: budget gate + extractive fallback (never silent trim)."""

    @staticmethod
    def limit_tokens(*, model_tier: str) -> int:
        return context_limit_tokens(model_tier=model_tier)

    @classmethod
    def threshold_tokens(cls, *, model_tier: str) -> int:
        limit = cls.limit_tokens(model_tier=model_tier)
        return max(1, int(limit * COMPACT_THRESHOLD_RATIO))

    @classmethod
    def needs_compact(cls, *, tokens: int, model_tier: str) -> bool:
        return tokens >= cls.threshold_tokens(model_tier=model_tier)

    @staticmethod
    def package_tokens(*, dialog: str, goal: str, plan: str, last_results: str) -> int:
        """Token count of the compactable package (dialog dominates growth)."""
        parts = (dialog, goal, plan, last_results)
        return sum(count_tokens(part) for part in parts if part.strip())

    @staticmethod
    def extractive_summary(dialog: str, *, tokens_before: int) -> str:
        """Deterministic compact with an explicit marker — not silent truncation."""
        stripped = dialog.strip()
        if not stripped:
            return ""
        if len(stripped) <= _EXTRACTIVE_HEAD_CHARS + _EXTRACTIVE_TAIL_CHARS:
            marker = f"[context_compacted method=extractive tokens_before={tokens_before} note=under_slice_budget]\n"
            return f"{marker}{stripped}"

        head = stripped[:_EXTRACTIVE_HEAD_CHARS].rstrip()
        tail = stripped[-_EXTRACTIVE_TAIL_CHARS:].lstrip()
        omitted = max(0, len(stripped) - _EXTRACTIVE_HEAD_CHARS - _EXTRACTIVE_TAIL_CHARS)
        marker = f"[context_compacted method=extractive tokens_before={tokens_before} omitted_chars={omitted}]\n"
        return f"{marker}{head}\n\n[... middle omitted by compact ...]\n\n{tail}"

    @staticmethod
    def dedupe_exact_lines(dialog: str) -> str:
        """Exact-line dedupe after normalize (065.4); order preserved."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in dialog.splitlines():
            line = " ".join(raw.split())
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
        return "\n".join(out)
