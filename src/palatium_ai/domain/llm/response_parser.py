# src/palatium_ai/domain/llm/response_parser.py

"""Парсер ответов LLM с автоматическим восстановлением."""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from structlog import get_logger

from palatium_ai.domain.llm.json_codec import loads_llm_json

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


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

    if not isinstance(payload, dict):
        logger.warning("LLM response is not a JSON object", type=type(payload).__name__)
        raise ValueError("LLM response must be a JSON object")

    if extract_nested and "document" in payload and "blocks" not in payload:
        payload = payload["document"]
        if not isinstance(payload, dict):
            logger.warning("Extracted 'document' is not a JSON object")
            raise ValueError("Extracted 'document' must be a JSON object")

    defaults = _resolve_defaults(default_factory) if default_factory else None

    if defaults:
        payload = _apply_defaults(payload, defaults)

    try:
        return model_class.model_validate(payload)
    except ValidationError as e:
        logger.warning(
            "LLM response validation failed",
            errors=str(e),
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
                errors=str(e2),
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
