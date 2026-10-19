# src/palatium_ai/domain/llm/structured_output.py

"""json_schema call invariant (one place for harness and the LLM adapter)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

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


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return ``model``'s JSON Schema shaped for ``strict: True`` providers.

    OpenAI / Anthropic strict mode requires every object to list all of its
    properties in ``required`` and to set ``additionalProperties: false``.
    Pydantic omits fields that carry a default from ``required`` and leaks the
    ``default`` keyword. Sending the runtime schema as-is with ``strict: True``
    made the model treat defaulted fields (e.g. ``ContentDocument.blocks``) as
    optional and drop them entirely — so we normalise here.

    This is the single point that owns the structured-output contract: pure,
    deterministic and unit-tested once.
    """
    return cast("dict[str, Any]", _strictify(model.model_json_schema()))


def _strictify(node: Any) -> Any:
    """Recursively enforce the strict-mode contract on a JSON Schema node.

    ``default`` is dropped (it is what makes the model skip a field). Every
    object with explicit ``properties`` gets ``additionalProperties: false`` and
    a full ``required`` list. Map-shaped nodes (``additionalProperties`` as a
    schema, no ``properties``) are left untouched — forcing them to object with
    fixed keys would reject the free-form payload they exist to carry.
    """
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {key: _strictify(value) for key, value in node.items() if key != "default"}
    if result.get("type") == "object" and "properties" in result:
        result["additionalProperties"] = False
        result["required"] = list(result["properties"].keys())
    return result
