# src/palatium_ai/domain/policies/dialog_correction.py

"""Strip superseded in-dialog claims before they reach the LLM (W10 P1.1).

Big Tech 2026: when the user revises a prior assertion in the same thread, the
old value must not stay co-present in the prompt — models otherwise hedge and
leak both (ORION-7 after VEGA-9). Detection is structural subject-overlap via
``MemoryMutationPolicy`` (055: no phrase lists like «стоп|ошибся»).
"""

from __future__ import annotations

from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.memory_mutation import MemoryMutationPolicy

#: Shared tokens / earlier tokens — enough to treat two assertions as one slot.
#: Lower than medium-memory ``MIN_EXISTING_OVERLAP`` (0.6): dialog corrections are
#: short («клиент — X» → «клиент — Y») and share fewer tokens.
CORRECTION_SUBJECT_RATIO = 0.4


class DialogCorrectionPolicy:
    """Pure policy: redact superseded user turns and intervening assistant acks."""

    @classmethod
    def apply(cls, window: DialogTurnWindow) -> DialogTurnWindow:
        """Return a copy whose ``turns`` omit retracted claims (idempotent)."""
        redacted = cls.redact_superseded(window.turns)
        if redacted == window.turns:
            return window
        return window.model_copy(update={"turns": redacted})

    @classmethod
    def filter_superseded_texts(
        cls,
        texts: tuple[str, ...] | list[str],
        turns: tuple[DialogTurn, ...],
    ) -> tuple[str, ...]:
        """Drop recall/scratchpad pins that a later dialog assertion revises (W10 2b).

        ``as_prompt_block`` redacts dialog turns, then re-pins medium/scratchpad
        hints — without this filter ORION-7 re-entered the prompt after VEGA-9.
        """
        assertions = tuple(turn.content for turn in turns if turn.role == "user" and not cls._is_question(turn.content))
        if not assertions:
            return tuple(str(t).strip() for t in texts if str(t).strip())
        kept: list[str] = []
        for raw in texts:
            text = str(raw).strip()
            if not text:
                continue
            if any(cls.supersedes(later, text) for later in assertions):
                continue
            kept.append(text)
        return tuple(kept)

    @classmethod
    def redact_superseded(cls, turns: tuple[DialogTurn, ...]) -> tuple[DialogTurn, ...]:
        if len(turns) < 2:
            return turns

        user_indices = [index for index, turn in enumerate(turns) if turn.role == "user"]
        drop: set[int] = set()

        for later_pos, later_index in enumerate(user_indices):
            later = turns[later_index]
            if cls._is_question(later.content):
                continue
            for earlier_index in user_indices[:later_pos]:
                if earlier_index in drop:
                    continue
                earlier = turns[earlier_index]
                if not cls.supersedes(later.content, earlier.content):
                    continue
                drop.add(earlier_index)
                # Intervening assistant acks of the old claim — drop wholesale.
                for mid in range(earlier_index + 1, later_index):
                    if turns[mid].role == "assistant":
                        drop.add(mid)

        if not drop:
            return turns
        return tuple(turn for index, turn in enumerate(turns) if index not in drop)

    @classmethod
    def supersedes(cls, later: str, earlier: str) -> bool:
        """True when ``later`` revises the same subject slot as ``earlier``."""
        if cls._is_question(later):
            return False
        left = MemoryMutationPolicy.normalize_text(later)
        right = MemoryMutationPolicy.normalize_text(earlier)
        if not left or not right or left.casefold() == right.casefold():
            return False
        later_tok = MemoryMutationPolicy.query_tokens(left)
        earlier_tok = MemoryMutationPolicy.query_tokens(right)
        if not later_tok or not earlier_tok:
            return False
        shared = later_tok & earlier_tok
        if not shared:
            return False
        if len(shared) / len(earlier_tok) < CORRECTION_SUBJECT_RATIO:
            return False
        # Value must change: later introduces tokens absent from earlier.
        return bool(later_tok - earlier_tok)

    @staticmethod
    def _is_question(text: str) -> bool:
        stripped = text.strip()
        return bool(stripped) and stripped.endswith("?")


__all__ = ["CORRECTION_SUBJECT_RATIO", "DialogCorrectionPolicy"]
