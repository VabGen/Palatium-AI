# src/palatium_ai/core/logging/context.py

"""Модуль context содержит контекстные переменные для сквозной трассировки запросов."""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
