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


class VisionUnsupportedError(PalatiumError):
    """An image message reached a path that cannot carry it (ADR 0007).

    Capability gap, not an outage: a fallback chain must move on to the next
    provider without opening the failed one's circuit breaker, and a single
    provider must fail closed instead of silently dropping the image.
    """

    def __init__(self, reason: str = "model or provider does not accept image messages") -> None:
        self.reason = reason
        super().__init__(reason)


class VisionImageUnavailableError(PalatiumError):
    """An approved image part could not be turned into bytes (ADR 0007).

    Raised by the blob-backed source: the object is gone, the store reports a media
    type the part never claimed, or the payload is outside the vision byte cap.
    Fail closed — a call without the image would answer "the picture is empty".
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"vision image unavailable: {reason}")
