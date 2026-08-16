# src/palatium_ai/__init__.py

"""palatium-ai — интеллектуальный офисный помощник."""

from importlib.metadata import PackageNotFoundError, version

from .core.logging import logger, setup_logging_from_settings

try:
    __version__ = version("palatium-ai")
except PackageNotFoundError:
    __version__ = "0.0.0"

setup_logging_from_settings()

__all__ = ["__version__", "logger"]
