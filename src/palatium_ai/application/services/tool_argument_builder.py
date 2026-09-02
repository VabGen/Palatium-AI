# src/palatium_ai/application/services/tool_argument_builder.py

"""Schema-driven argument builder for MCP tool calls."""

from __future__ import annotations

import contextlib
import json
import logging

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from palatium_ai.core.exceptions import AuditWriteDegradedError
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.argument_policy import UnsafeToolArgumentError, assert_arguments_safe

if TYPE_CHECKING:
    from palatium_ai.domain.mcp.models import MCPToolDescriptor
    from palatium_ai.domain.ports.llm import LLMPort

logger = logging.getLogger(__name__)


class ToolArgumentBuildError(ValueError):
    """LLM failed to produce schema-valid tool arguments after retries.

    Callers MUST catch this and degrade gracefully (ToolResult(ERROR) +
    next_action_hint) — never let it surface as HTTP 500.
    """


_MAX_ARG_RETRIES = 1
_REASON_HEAD_LEN = 500


class ToolArgumentBuilder:
    """Строит args для MCP tool на основе JSON Schema 2020-12.

    Контракт отказного пути:
        invalid args -> retry(1) c feedback -> ToolArgumentBuildError.

    Audit-события (rejected/validated) — best effort: деградация аудита
    (AuditWriteDegradedError) НЕ влияет на построение аргументов и не
    конвертируется в ToolArgumentBuildError, чтобы не смешивать «модель
    выдала мусор» и «диск недоступен» в одном коде ошибки.
    """

    def __init__(self, llm: LLMPort, *, max_retries: int = _MAX_ARG_RETRIES) -> None:
        self._llm = llm
        self._max_retries = max_retries

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
        """Генерирует JSON arguments object, соответствующий tool schema.

        Raises
        ------
        ToolArgumentBuildError
            Если после всех retry аргументы не прошли валидацию.
            Обработчик обязан вернуть пользователю fallback-ответ.

        """
        messages = self._build_messages(
            descriptor=descriptor,
            user_text=user_text,
            route_plan=route_plan,
            task_kind=task_kind,
            candidate_capabilities=candidate_capabilities,
        )

        last_error: ValueError | UnsafeToolArgumentError | None = None
        for attempt in range(self._max_retries + 1):
            completion = await self._llm.generate(messages, temperature=0.0, response_format="json_object")
            try:
                arguments = _parse_arguments_object(completion.content)
                _validate_arguments_against_schema(arguments, descriptor.input_schema)
                assert_arguments_safe(arguments)
            except (ValueError, UnsafeToolArgumentError) as exc:
                last_error = exc
                logger.warning(
                    "tool args rejected (tool=%s attempt=%d/%d): %s",
                    descriptor.name,
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                await _emit_builder_audit_event(
                    conversation_id=conversation_id or descriptor.name,
                    event="tool_argument_builder_rejected",
                    metadata={
                        "tool_name": descriptor.name,
                        "reason": str(exc)[:_REASON_HEAD_LEN],
                        "attempt": str(attempt),
                    },
                )
                if attempt < self._max_retries:
                    messages = [
                        *messages,
                        ChatMessage(role="assistant", content=completion.content),
                        ChatMessage(
                            role="user",
                            content=(
                                f"Твои аргументы отклонены: {exc}\n"
                                f"Верни JSON object со ВСЕМИ required-полями "
                                f"схемы инструмента '{descriptor.name}'. "
                                "Только JSON, без пояснений."
                            ),
                        ),
                    ]
                continue

            await _emit_builder_audit_event(
                conversation_id=conversation_id or descriptor.name,
                event="tool_argument_builder_validated",
                metadata={
                    "tool_name": descriptor.name,
                    "attempt": str(attempt),
                },
            )
            return arguments

        raise ToolArgumentBuildError(
            f"Tool '{descriptor.name}': argument generation failed "
            f"after {self._max_retries + 1} attempt(s): {last_error}"
        )

    def _build_messages(
        self,
        *,
        descriptor: MCPToolDescriptor,
        user_text: str,
        route_plan: str,
        task_kind: str,
        candidate_capabilities: tuple[str, ...],
    ) -> list[ChatMessage]:
        """System+user pair; контекст отделён от задания для качества генерации."""
        context_block = json.dumps(
            {
                "tool_name": descriptor.name,
                "tool_description": descriptor.description,
                "input_schema": descriptor.input_schema,
                "route_plan": route_plan,
                "task_kind": task_kind,
                "candidate_capabilities": candidate_capabilities,
            },
            ensure_ascii=False,
        )
        return [
            ChatMessage(
                role="system",
                content=(
                    "You build arguments for an MCP tool call. "
                    "Return ONLY a valid JSON object that matches the given "
                    "JSON Schema 2020-12. Every required property of the schema "
                    "MUST be present. "
                    "Never include secrets, passwords, API keys, tokens, or credentials."
                ),
            ),
            ChatMessage(role="user", content=f"TOOL CONTEXT:\n{context_block}"),
            ChatMessage(
                role="user",
                content=(f"USER REQUEST (build 'arguments' from it):\n{user_text}"),
            ),
        ]


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


async def _emit_builder_audit_event(
    *,
    conversation_id: str,
    event: str,
    metadata: dict[str, str],
) -> None:
    """Пишет audit-событие по результату schema guardrail.

    Audit — best effort относительно этого сервиса:
    - AuditWriteDegradedError (диск недоступен, событие в dead-letter) →
      глотается: деградация аудита не должна ломать построение аргументов
      и превращаться в 500 или в ToolArgumentBuildError.
    - AuditChainIntegrityError (повреждение/подмена цепочки) →
      пробрасывается: это tamper-сигнал, его обязан увидеть верхний
      обработчик, а не потерять внутри builder'а.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with contextlib.suppress(AuditWriteDegradedError):
        await get_audit_logger().append_async(
            timestamp=timestamp,
            conversation_id=conversation_id,
            event=event,
            metadata=metadata,
        )
