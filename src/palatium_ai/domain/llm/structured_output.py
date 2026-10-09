# src/palatium_ai/domain/llm/structured_output.py

"""json_schema call invariant (one place for harness and the LLM adapter)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.domain.llm.models import LLMResponseFormat


def response_model_for_schema(
    response_format: LLMResponseFormat | None,
    response_model: type[BaseModel] | None,
) -> type[BaseModel] | None:
    """Return the model for json_schema, or None for every other mode.

    json_schema without a model is a programmer error and is raised before any provider call.
    """
    if response_format != "json_schema":
        return None
    if response_model is None:
        raise ValueError("response_model is required when response_format is 'json_schema'")
    return response_model


def assert_json_schema_model(
    response_format: LLMResponseFormat | None,
    response_model: type[BaseModel] | None,
) -> None:
    """Harness-facing alias: raise before the adapter when json_schema has no model."""
    response_model_for_schema(response_format, response_model)
