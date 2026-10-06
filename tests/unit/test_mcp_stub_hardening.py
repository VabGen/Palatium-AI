"""MCP stub hardening: request body cap + per-client rate limit (P1-8, 020).

These middlewares run in a separate process from the platform, so they are exercised
directly as ASGI callables — no need to boot uvicorn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_servers import mcp_stub_runtime
from mcp_servers.mcp_stub_hardening import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    harden_asgi_app,
)

_MCP_ROOT = Path(__file__).resolve().parents[2] / "mcp_servers"
_MAX_BODY_BYTES = 1024
_ENV_NAMES = ("MCP_MAX_BODY_BYTES", "MCP_RATE_LIMIT", "MCP_RATE_LIMIT_WINDOW_SECONDS")


@pytest.fixture(autouse=True)
def _clear_hardening_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env-driven limits must not leak between tests."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _echo_app() -> Starlette:
    async def echo_endpoint(request: Any) -> JSONResponse:
        body = await request.body()
        return JSONResponse({"received": len(body)})

    async def health_endpoint(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[Route("/", echo_endpoint, methods=["POST"]), Route("/health", health_endpoint)])


# --- body size -------------------------------------------------------------------


def test_body_within_limit_passes_through() -> None:
    app = BodySizeLimitMiddleware(_echo_app(), max_bytes=_MAX_BODY_BYTES)
    response = TestClient(app).post("/", content=b"x" * 100, headers={"content-length": "100"})
    assert response.status_code == 200
    assert response.json() == {"received": 100}


def test_body_over_declared_content_length_is_rejected() -> None:
    app = BodySizeLimitMiddleware(_echo_app(), max_bytes=_MAX_BODY_BYTES)
    response = TestClient(app).post("/", content=b"x" * (_MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_chunked_body_without_content_length_is_capped() -> None:
    """Omitting Content-Length must not bypass the cap (streaming guard).

    A generator body makes httpx use ``Transfer-Encoding: chunked``, so the declared
    length shortcut never fires and only the byte counter can stop it.
    """

    def chunks() -> Any:
        for _ in range(5):
            yield b"y" * 512  # 2560 bytes > 1024

    app = BodySizeLimitMiddleware(_echo_app(), max_bytes=_MAX_BODY_BYTES)
    response = TestClient(app).post("/", content=chunks())
    assert response.status_code == 413


@pytest.mark.asyncio()
async def test_body_size_limit_passes_non_http_scope_through() -> None:
    """Lifespan must pass through untouched or the app never starts."""
    seen: list[str] = []

    async def fake_app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    middleware = BodySizeLimitMiddleware(fake_app, max_bytes=_MAX_BODY_BYTES)
    await middleware({"type": "lifespan"}, None, None)  # type: ignore[arg-type]
    assert seen == ["lifespan"]


# --- rate limit ------------------------------------------------------------------


def test_rate_limit_allows_up_to_budget_then_rejects() -> None:
    app = RateLimitMiddleware(_echo_app(), limit=3, window_seconds=60)
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/", content=b"{}").status_code == 200

    response = client.post("/", content=b"{}")
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) >= 1


def test_rate_limit_exempts_health_probe() -> None:
    """A throttled probe would restart a healthy container — /health must never 429."""
    app = RateLimitMiddleware(_echo_app(), limit=1, window_seconds=60)
    client = TestClient(app)
    for _ in range(10):
        assert client.get("/health").status_code == 200


def test_rate_limit_window_expiry_releases_budget() -> None:
    """After the window slides past, previously counted hits must be pruned."""
    limiter = RateLimitMiddleware(_echo_app(), limit=1, window_seconds=60)
    assert limiter._register_hit("ip:test") is None  # first hit allowed
    assert limiter._register_hit("ip:test") is not None  # budget spent

    # Backdate the recorded hit past the window instead of patching the global clock.
    limiter._hits["ip:test"][0] -= 61.0
    assert limiter._register_hit("ip:test") is None  # pruned → allowed again


def test_rate_limit_keys_are_per_client() -> None:
    """One noisy client must not consume another client's budget."""
    limiter = RateLimitMiddleware(_echo_app(), limit=1, window_seconds=60)
    assert limiter._register_hit("ip:10.0.0.1") is None
    assert limiter._register_hit("ip:10.0.0.2") is None


# --- composition -----------------------------------------------------------------


def test_harden_asgi_app_combines_both_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_MAX_BODY_BYTES", "256")
    monkeypatch.setenv("MCP_RATE_LIMIT", "3")
    monkeypatch.setenv("MCP_RATE_LIMIT_WINDOW_SECONDS", "60")

    client = TestClient(harden_asgi_app(_echo_app()))

    # Body cap fires on the first request, while the rate budget still has room.
    assert client.post("/", content=b"z" * 999).status_code == 413
    # Rate limiting is the outer layer, so it counts that request too: 2 more allowed.
    assert client.post("/", content=b"z" * 10).status_code == 200
    assert client.post("/", content=b"z" * 10).status_code == 200
    assert client.post("/", content=b"z" * 10).status_code == 429


@pytest.mark.parametrize("bad_value", ("not-a-number", "0", "-5", ""))
def test_harden_asgi_app_falls_back_on_bad_env(monkeypatch: pytest.MonkeyPatch, bad_value: str) -> None:
    """Invalid/blank env must fall back to defaults, never disable a guard."""
    for name in ("MCP_RATE_LIMIT", "MCP_RATE_LIMIT_WINDOW_SECONDS"):
        monkeypatch.setenv(name, bad_value)
    monkeypatch.setenv("MCP_MAX_BODY_BYTES", bad_value)

    client = TestClient(harden_asgi_app(_echo_app()))
    assert client.post("/", content=b"a" * 8).status_code == 200


def test_stub_runtime_and_gateway_apply_hardening() -> None:
    """Wiring guard: a future refactor must not silently drop the middleware."""
    stub_source = Path(mcp_stub_runtime.__file__).read_text(encoding="utf-8")
    assert "from mcp_servers.mcp_stub_hardening import harden_asgi_app" in stub_source
    assert "return harden_asgi_app(" in stub_source

    gateway_source = (_MCP_ROOT / "gateway" / "gateway_mcp_server.py").read_text(encoding="utf-8")
    assert "harden_asgi_app(" in gateway_source


def test_stub_modules_use_package_qualified_sibling_imports() -> None:
    """Siblings are imported as `mcp_servers.*`, never flat — one layout for dev + image.

    Flat sibling imports only resolve with `mcp_servers/` on `sys.path`, which shadows the
    stdlib `platform` module (the stubs ship `mcp_servers/platform/`), so the flat form is
    not merely untidy — it breaks unrelated imports (000/070).
    """
    offenders: list[str] = []
    for path in sorted(_MCP_ROOT.rglob("*.py")):
        if "JavaEdms" in path.parts:  # rule 090: read-only reference, not our code
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            bare = line.strip()
            if bare.startswith(("from mcp_stub_", "import mcp_stub_")):
                offenders.append(f"{path.relative_to(_MCP_ROOT).as_posix()}: {bare}")

    assert not offenders, f"flat sibling imports found (use `mcp_servers.…`): {offenders}"


def test_image_and_compose_launch_stubs_as_packages() -> None:
    """Dockerfile + Compose must name package modules, matching the copied layout."""
    repo_root = _MCP_ROOT.parent
    dockerfile = (_MCP_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    # Image keeps the package tree and puts /app on the path, so `mcp_servers.…` resolves.
    assert "COPY --chown=mcp:mcp mcp_servers/*.py /app/mcp_servers/" in dockerfile
    assert "PYTHONPATH=/app/src:/app" in dockerfile
    assert "ARG MCP_MODULE=mcp_servers." in dockerfile

    module_args = [line.split("MCP_MODULE:", 1)[1].strip() for line in compose.splitlines() if "MCP_MODULE:" in line]
    assert module_args, "no MCP_MODULE args found in docker-compose.yml"
    assert all(value.startswith("mcp_servers.") for value in module_args), module_args
