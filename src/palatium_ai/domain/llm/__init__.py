# src/palatium_ai/domain/llm/__init__.py

"""Доменные модели LLM."""

from .errors import StructuredOutputUnsupportedError, VisionImageUnavailableError, VisionUnsupportedError
from .models import (
    VISION_IMAGE_MIMES,
    ChatMessage,
    ImageMime,
    ImagePart,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)

__all__ = [
    "VISION_IMAGE_MIMES",
    "ChatMessage",
    "ImageMime",
    "ImagePart",
    "LLMCompletion",
    "LLMResponseFormat",
    "LLMStreamDelta",
    "LLMUsage",
    "StructuredOutputUnsupportedError",
    "VisionImageUnavailableError",
    "VisionUnsupportedError",
]
