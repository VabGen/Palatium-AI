# src/palatium_ai/domain/memory/types.py

"""Типы записей эпизодической памяти (060) — единственный источник."""

from __future__ import annotations

from typing import Literal

MemoryType = Literal["preference", "fact", "incident", "episode"]

#: Value marker for a write a human explicitly approved («запомни …», 020/060).
#: Hot-path recall treats these as deliberate durable memory: an approved fact may
#: cross threads, while facts *inferred* by extract stay thread-scoped (P0-B bleed).
MEMORY_EXPLICIT_WRITE_KEY = "explicit_write"

__all__ = ["MEMORY_EXPLICIT_WRITE_KEY", "MemoryType"]
