# src/palatium_ai/core/logging/filters.py

"""Модуль filters содержит класс SuppressFilter для фильтрации логов."""

import logging


class SuppressFilter(logging.Filter):
    """Фильтр, который не пропускает логи из указанных модулей."""

    def __init__(self, modules: list[str]) -> None:
        self.modules = modules

    def filter(self, record: logging.LogRecord) -> bool:
        """Возвращает True, если запись не из указанных модулей."""
        return not any(record.name.startswith(m) for m in self.modules)
