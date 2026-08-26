# src/palatium_ai/application/services/tool_argument_builder.py

"""Schema-driven argument builder for MCP tool calls."""

from __future__ import annotations

import json

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.argument_policy import UnsafeToolArgumentError, assert_arguments_safe

if TYPE_CHECKING:
    from palatium_ai.domain.mcp.models import MCPToolDescriptor
    from palatium_ai.domain.ports.llm import LLMPort


class ToolArgumentBuilder:
    """Строит args для MCP tool на основе JSON Schema 2020-12."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def build_arguments(
        self,
        *,
        descriptor: MCPToolDescriptor,
        user_text: str,
        route_plan: str,
        task_kind: str,
        candidate_capabilities: tuple[str, ...],
        conversation_id: str | None = None,
    ) -> dict[str, object]:
        """Генерирует JSON arguments object, соответствующий tool schema."""
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You build arguments for an MCP tool call. "
                    "Return ONLY a valid JSON object that matches the given JSON Schema 2020-12. "
                    "Never include secrets, passwords, API keys, tokens, or credentials."
                ),
            ),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "tool_name": descriptor.name,
                        "tool_description": descriptor.description,
                        "input_schema": descriptor.input_schema,
                        "user_text": user_text,
                        "route_plan": route_plan,
                        "task_kind": task_kind,
                        "candidate_capabilities": candidate_capabilities,
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
        completion = await self._llm.generate(messages, temperature=0.0, response_format="json_object")
        try:
            arguments = _parse_arguments_object(completion.content)
            _validate_arguments_against_schema(arguments, descriptor.input_schema)
            assert_arguments_safe(arguments)
        except (ValueError, UnsafeToolArgumentError) as exc:
            await _write_builder_audit_event(
                conversation_id=conversation_id or descriptor.name,
                event="tool_argument_builder_rejected",
                metadata={
                    "tool_name": descriptor.name,
                    "reason": str(exc)[:500],
                },
            )
            raise
        await _write_builder_audit_event(
            conversation_id=conversation_id or descriptor.name,
            event="tool_argument_builder_validated",
            metadata={
                "tool_name": descriptor.name,
            },
        )
        return arguments


def _parse_arguments_object(raw_content: str) -> dict[str, object]:
    """Парсит JSON object из ответа LLM."""
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        raise ValueError("Tool argument builder must return a JSON object")
    return payload


def _validate_arguments_against_schema(
    arguments: dict[str, object],
    schema: dict[str, object],
) -> None:
    """Проверяет LLM-сгенерированные аргументы по JSON Schema."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=str)
    if not errors:
        return

    first_error = errors[0]
    location = ".".join(str(part) for part in first_error.path) or "<root>"
    raise ValueError(f"Generated tool arguments failed schema validation at {location}: {first_error.message}")


async def _write_builder_audit_event(
    *,
    conversation_id: str,
    event: str,
    metadata: dict[str, str],
) -> None:
    """Пишет audit-событие по результату schema guardrail."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )
