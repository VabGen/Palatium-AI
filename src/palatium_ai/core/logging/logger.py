# src/palatium_ai/core/logging/logger.py

"""Модуль logger содержит функцию get_logger и корневой логгер."""

from typing import cast

import structlog


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Возвращает структурированный логгер с именем модуля."""
    if name is None:
        name = __name__
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))


logger = get_logger("palatium_ai")
