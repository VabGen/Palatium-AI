# src/palatium_ai/domain/llm/response_parser.py

"""Парсер ответов LLM с автоматическим восстановлением."""

import json

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from structlog import get_logger

from palatium_ai.domain.llm.json_codec import LLMJSONError, loads_llm_json

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def compact_validation_error(exc: Exception) -> str:
    """``field: message`` pairs — the repair prompt/log needs the defect, not the payload.

    ``str(ValidationError)`` embeds ``input_value`` (the model's prose), which then
    lands in warning logs (020, 040).
    """
    if isinstance(exc, ValidationError):
        pairs = ({"field": ".".join(str(part) for part in err["loc"]), "error": err["msg"]} for err in exc.errors())
        return json.dumps(list(pairs), ensure_ascii=False)
    reason = getattr(exc, "reason", None)
    return str(reason) if isinstance(reason, str) else type(exc).__name__


def parse_llm_response[T: BaseModel](
    raw_content: str,
    model_class: type[T],
    *,
    default_factory: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    extract_nested: bool = True,
    repair: bool = True,
) -> T:
    """
    Универсальный парсер LLM-ответа с автоматическим восстановлением.

    "Args":
        raw_content: Сырой ответ LLM (строка с JSON).
        model_class: Класс Pydantic-модели для валидации.
        default_factory: Словарь или вызываемый объект, возвращающий словарь
            со значениями по умолчанию для отсутствующих полей.
        extract_nested: Если True и payload содержит ключ "document",
            а сам payload не содержит "blocks", то извлекает вложенный документ.
        repair: Если True, при ошибке валидации повторно применяет дефолты
            и пытается снова.

    "Returns":
        Валидный экземпляр model_class.

    "Raises":
        ValidationError: Если валидация не удалась даже после repair.
        ValueError: Если payload не является JSON-объектом.
    """
    payload = loads_llm_json(raw_content)
    return parse_llm_payload(
        payload,
        model_class,
        default_factory=default_factory,
        extract_nested=extract_nested,
        repair=repair,
    )


def parse_llm_payload[T: BaseModel](
    payload: object,
    model_class: type[T],
    *,
    default_factory: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    extract_nested: bool = True,
    repair: bool = True,
) -> T:
    """Validate an already-decoded payload — the hook for callers that normalise first.

    The Formatter strips layout values the UI registry does not know (unknown icon
    names) before validation, so it cannot use :func:`parse_llm_response`, which owns
    decoding. Both entry points share this single validation/defaults contract.
    """
    if not isinstance(payload, dict):
        logger.warning("LLM response is not a JSON object", type=type(payload).__name__)
        raise LLMJSONError("LLM response must be a JSON object", reason="not_object")

    if extract_nested and "document" in payload and "blocks" not in payload:
        payload = payload["document"]
        if not isinstance(payload, dict):
            logger.warning("Extracted 'document' is not a JSON object")
            raise LLMJSONError("Extracted 'document' must be a JSON object", reason="not_object")

    defaults = _resolve_defaults(default_factory) if default_factory else None

    if defaults:
        payload = _apply_defaults(payload, defaults)

    try:
        return model_class.model_validate(payload)
    except ValidationError as e:
        logger.warning(
            "LLM response validation failed",
            errors=compact_validation_error(e),
            model=model_class.__name__,
        )
        if not repair or not defaults:
            raise

        payload = _apply_defaults(payload, defaults)
        try:
            return model_class.model_validate(payload)
        except ValidationError as e2:
            logger.error(
                "LLM response validation failed after repair",
                errors=compact_validation_error(e2),
                model=model_class.__name__,
            )
            raise e2 from None


def _resolve_defaults(default_factory: dict[str, Any] | Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Преобразует default_factory в словарь."""
    return default_factory() if callable(default_factory) else default_factory


def _apply_defaults(payload: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно применяет дефолты к payload (только первый уровень)."""
    result = payload.copy()
    for key, value in defaults.items():
        if key not in result:
            result[key] = value
    return result
