# src/palatium_ai/presentation/websockets/__init__.py

"""WebSocket endpoints for session/HITL push."""

from .session import register_websocket_routes

__all__ = ["register_websocket_routes"]
