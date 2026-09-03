# src/palatium_ai/domain/memory/types.py

"""Типы записей эпизодической памяти (060) — единственный источник."""

from __future__ import annotations

from typing import Literal

MemoryType = Literal["preference", "fact", "incident", "episode"]

__all__ = ["MemoryType"]
