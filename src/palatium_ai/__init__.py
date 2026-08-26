# src/palatium_ai/__init__.py

"""palatium-ai — интеллектуальный офисный помощник."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("palatium-ai")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
