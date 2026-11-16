# src/palatium_ai/infrastructure/parsing/pymupdf_compat.py

"""PyMuPDF access with a stable module name and quiet diagnostics.

Two loose ends made every PDF turn look broken (P5):

1. ``import fitz`` is a deprecated alias that prints
   ``The `fitz` API is deprecated …`` to stderr on import — once per process, attributed
   to whichever adapter happened to touch the first document. The real module name is
   ``pymupdf``; ``fitz`` stays only as a fallback for an older pin.
2. MuPDF reports recoverable structure problems on stderr, bypassing structlog: a
   duplicate ``/Info`` key prints ``Multiple definitions in dictionary`` once per page,
   so a perfectly readable scan looks like a parse failure in the container log.

Warnings are silenced (they are never actionable — the document still parses), errors
are not: a genuine render failure must stay visible (035, 040).
"""

from __future__ import annotations

import importlib.util
import threading

from types import ModuleType

_lock = threading.Lock()
_module: ModuleType | None = None


def pymupdf() -> ModuleType:
    """Return the PyMuPDF module, importing it once.

    Raises ``ImportError`` when the ``attachments`` extra is absent: callers convert
    that into a typed rejection, never into a crash mid-document (035).
    """
    global _module
    if _module is not None:
        return _module
    with _lock:
        if _module is None:
            resolved = _import_module()
            _quiet_diagnostics(resolved)
            _module = resolved
    return _module


def pymupdf_available() -> bool:
    """Whether PyMuPDF can be imported, without importing it (factory probe)."""
    return bool(_find_spec("pymupdf") or _find_spec("fitz"))


def _import_module() -> ModuleType:
    """Resolve PyMuPDF by name: ``pymupdf`` first, the legacy ``fitz`` alias second."""
    for module_name in ("pymupdf", "fitz"):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue
    msg = "pymupdf is not installed; install the 'attachments' extra"
    raise ImportError(msg)


def _find_spec(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ImportError, ValueError:
        return False


def _quiet_diagnostics(module: ModuleType) -> None:
    """Disable MuPDF's stderr warnings; keep error reporting intact."""
    tools = getattr(module, "TOOLS", None)
    display_warnings = getattr(tools, "mupdf_display_warnings", None)
    if callable(display_warnings):
        display_warnings(False)


__all__ = ["pymupdf", "pymupdf_available"]
