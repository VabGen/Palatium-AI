# src/palatium_ai/domain/policies/formatter_fast_path.py

"""When Formatter may emit a ContentDocument without an LLM call (055).

Big Tech presentation layer (Anthropic / Copilot / ADK): the user-visible
document is the product surface — soft latency degrade must not flatten it, and
hop budget never drives ``skip_llm``.

Sanctioned skips:
- *passthrough*: a short, already-plain answer whose deterministic emit is
  paragraphs only. There is nothing to compile — an LLM pass could only add
  structure the content does not have (a one-line joke turned into an icon list).
- *verbatim*: Intent tagged ``verbatim_extraction`` — the worker body *is* the
  deliverable (file extract). Length / structure / locale must not force an LLM
  rewrite that replaces the already-streamed text.

The gate is on capabilities and worker answer shape, never on the user's wording
(055).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FormatterFastPathDecision(BaseModel):
    """Outcome of FormatterFastPathPolicy for one turn."""

    model_config = {"frozen": True}

    skip_llm: bool
    reason: str = Field(min_length=1, max_length=128)


class FormatterPassthroughSignals(BaseModel):
    """Facts about the turn the passthrough gate needs (computed by the caller)."""

    model_config = {"frozen": True}

    source_chars: int = Field(ge=0)
    # A failed / low-confidence worker leaves a placeholder, not an answer to show.
    worker_confident: bool = False
    source_is_plain_prose: bool = False
    locale_matches: bool = False
    requires_review: bool = False
    revision_requested: bool = False
    restructure_requested: bool = False
    # An explicit ``response_shape`` (not auto) is a composition request: deterministic
    # passthrough emits plain paragraphs, which would silently ignore it (ADR 0005).
    shape_requested: bool = False
    underspecification_kind: str = "none"
    # Intent tagged extract/full-text — show worker body as-is (ignore length/structure).
    verbatim_requested: bool = False


class FormatterFastPathPolicy:
    """Pure domain policy: Formatter LLM unless a short plain or verbatim answer can pass through."""

    @classmethod
    def decide(
        cls,
        *,
        source_content: str,
        requires_user_choice: bool = False,
        passthrough: FormatterPassthroughSignals | None = None,
        passthrough_max_chars: int = 0,
    ) -> FormatterFastPathDecision:
        """Return whether Formatter must call an LLM.

        Empty source and HITL choice always invoke the LLM (Formatter synthesizes
        or builds cards). ``passthrough_max_chars <= 0`` disables passthrough.
        """
        if requires_user_choice:
            return FormatterFastPathDecision(skip_llm=False, reason="requires_user_choice")
        blocker = cls._passthrough_blocker(
            source_content=source_content,
            passthrough=passthrough,
            max_chars=passthrough_max_chars,
        )
        if blocker is None:
            reason = (
                "passthrough_verbatim"
                if passthrough is not None and passthrough.verbatim_requested
                else "passthrough_plain_prose"
            )
            return FormatterFastPathDecision(skip_llm=True, reason=reason)
        return FormatterFastPathDecision(skip_llm=False, reason=blocker)

    @staticmethod
    def _passthrough_blocker(
        *,
        source_content: str,
        passthrough: FormatterPassthroughSignals | None,
        max_chars: int,
    ) -> str | None:
        if passthrough is None or max_chars <= 0 or not source_content.strip():
            return "presentation_requires_formatter_llm"
        if not passthrough.worker_confident:
            return "worker_not_confident"
        hard_stops = (
            (passthrough.requires_review, "requires_review"),
            (passthrough.revision_requested, "revision_requested"),
            (passthrough.restructure_requested, "restructure_requested"),
            (passthrough.shape_requested, "shape_requested"),
            (passthrough.underspecification_kind != "none", "underspecified"),
        )
        hard = next((reason for failed, reason in hard_stops if failed), None)
        if hard is not None:
            return hard
        if passthrough.verbatim_requested:
            return None
        soft_stops = (
            (passthrough.source_chars > max_chars, "source_exceeds_passthrough"),
            (not passthrough.source_is_plain_prose, "source_has_structure"),
            (not passthrough.locale_matches, "locale_mismatch"),
        )
        return next((reason for failed, reason in soft_stops if failed), None)
