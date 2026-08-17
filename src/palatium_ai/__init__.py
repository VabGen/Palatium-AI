# src/palatium_ai/__init__.py

"""palatium-ai — интеллектуальный офисный помощник."""

from importlib.metadata import PackageNotFoundError, version

from .core.config import get_settings
from .core.logging import logger, setup_logging

try:
    __version__ = version("palatium-ai")
except PackageNotFoundError:
    __version__ = "0.0.0"

settings = get_settings()
setup_logging(settings)

__all__ = ["__version__", "logger"]
