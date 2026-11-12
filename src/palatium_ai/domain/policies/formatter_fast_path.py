# src/palatium_ai/domain/policies/formatter_fast_path.py

"""When Formatter may emit a ContentDocument without an LLM call (055).

Big Tech presentation layer (Anthropic / Copilot / ADK): the user-visible
document is the product surface — soft latency degrade must not flatten it, and
hop budget never drives ``skip_llm``.

Sanctioned skips:
- *passthrough*: a short, already-plain answer whose deterministic emit is
  paragraphs only. There is nothing to compile — an LLM pass could only add
  structure the content does not have (a one-line joke turned into an icon list).
- *shaped worker*: worker GFM already has headings/lists — deterministic render;
  an LLM brand pass would replace the streamed draft with a thinner rewrite.
- *verbatim*: Intent tagged ``verbatim_extraction`` — the worker body *is* the
  deliverable (file extract). Length / structure / locale must not force an LLM
  rewrite that replaces the already-streamed text.
- *policy refusal*: deterministic user-facing copy from FileReference /
  GroundingPolicy (W10 P0.3 / P1.3). Confidence is 0.0 by contract; an LLM rewrite
  turns RU «файл не найден» into an English «please upload» (live att_not_found).

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
    # Worker GFM already has headings/lists — deterministic render, no brand rewrite.
    preserve_shaped_worker: bool = False
    # Worker body is a closed policy refusal (attachment unresolved / empty grounding).
    policy_refusal: bool = False


class FormatterFastPathPolicy:
    """Pure domain policy: Formatter LLM unless a short plain or shaped worker answer can pass through."""

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
            if passthrough is not None and passthrough.policy_refusal:
                reason = "passthrough_policy_refusal"
            elif passthrough is not None and passthrough.verbatim_requested:
                reason = "passthrough_verbatim"
            elif passthrough is not None and passthrough.preserve_shaped_worker:
                reason = "passthrough_shaped_worker"
            else:
                reason = "passthrough_plain_prose"
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
        # Policy refusals are the answer: ignore confidence / locale / length.
        if passthrough.policy_refusal:
            return None
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
        # Verbatim / already-shaped worker: length and structure must not force a
        # second writer that replaces the streamed draft (040 layout_shift).
        if passthrough.verbatim_requested or passthrough.preserve_shaped_worker:
            if not passthrough.locale_matches and not passthrough.verbatim_requested:
                return "locale_mismatch"
            return None
        soft_stops = (
            (passthrough.source_chars > max_chars, "source_exceeds_passthrough"),
            (not passthrough.source_is_plain_prose, "source_has_structure"),
            (not passthrough.locale_matches, "locale_mismatch"),
        )
        return next((reason for failed, reason in soft_stops if failed), None)
