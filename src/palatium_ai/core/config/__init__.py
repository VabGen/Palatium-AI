# src/palatium_ai/core/config/__init__.py

"""Модуль config экспортирует единый объект settings и функцию get_settings."""

from .settings import Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings"]
