# src/palatium_ai/domain/llm/errors.py

"""Typed LLM failures (035). Callers branch on the type, not on provider text."""

from __future__ import annotations

from palatium_ai.core.exceptions import PalatiumError


class StructuredOutputUnsupportedError(PalatiumError):
    """Provider rejected json_schema / strict structured output.

    This is a capability gap, not a bad completion and not a timeout.
    Callers may retry with ``json_object``. Invalid JSON after a successful
    json_schema call is a model error and must not be reported as this type.
    """

    def __init__(self, provider_message: str = "") -> None:
        self.provider_message = provider_message
        super().__init__("provider does not support json_schema structured output")
