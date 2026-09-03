# src/palatium_ai/infrastructure/web/__init__.py

"""Web search infrastructure adapters."""

from palatium_ai.infrastructure.web.http_web_search_port import HttpWebSearchPort
from palatium_ai.infrastructure.web.stub_web_search_port import StubWebSearchPort

__all__ = ["HttpWebSearchPort", "StubWebSearchPort"]
