# src/palatium_ai/presentation/resources.py

"""Общие presentation-layer helpers для доступа к app resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from palatium_ai.application.bootstrap import AppResources

if TYPE_CHECKING:
    from fastapi import FastAPI


def get_app_resources(app: FastAPI | Any) -> AppResources:
    """Возвращает ресурсы приложения из `app.state`."""
    resources = getattr(app.state, "resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("App resources are not initialized")
    return resources
