# src/palatium_ai/infrastructure/retention/_scalars.py

"""Coerce SECURITY DEFINER RPC scalars to int (mypy-safe; no unreachable ``or``)."""

from __future__ import annotations


def rpc_int(value: object) -> int:
    """Map RPC scalar → int; NULL → 0. Unexpected types raise (fail-closed)."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    msg = f"expected int-like RPC scalar, got {type(value).__name__}"
    raise TypeError(msg)
