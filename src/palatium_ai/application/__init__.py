# src/palatium_ai/application/__init__.py

# application/ (Приложение): use cases, bootstrap, orchestration.

from .bootstrap import AppResources, shutdown, startup
from .services.intent_service import IntentService
from .wiring import build_intent_service

__all__ = ["AppResources", "startup", "shutdown", "IntentService", "build_intent_service"]
