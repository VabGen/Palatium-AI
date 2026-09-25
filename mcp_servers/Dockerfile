# =============================================================================
# MCP stub / gateway servers — FastMCP Streamable HTTP
# =============================================================================
#
# Stub (from repo root):
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=edms --build-arg MCP_MODULE=mcp_servers.edms.edms_mcp_server \
#     --build-arg MCP_PORT=8080 -t palatium-mcp-edms:local .
#
# Gateway (Phase 6):
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=gateway --build-arg MCP_MODULE=mcp_servers.gateway.gateway_mcp_server \
#     --build-arg MCP_PORT=8090 -t palatium-mcp-gateway:local .
#
# Prefer Compose: docker-compose.yml (profile docker-mcp / mcp-gateway).
#
# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS runtime

ARG MCP_NAME=edms
ARG MCP_MODULE=mcp_servers.edms.edms_mcp_server
ARG MCP_PORT=8080

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_NAME=${MCP_NAME} \
    MCP_MODULE=${MCP_MODULE} \
    MCP_PORT=${MCP_PORT} \
    PYTHONPATH=/app/src:/app

LABEL org.opencontainers.image.title="palatium-mcp-${MCP_NAME}" \
      org.opencontainers.image.description="Palatium AI MCP stub server (${MCP_NAME})" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Pin exact versions — mirror poetry.lock.
#
# Required by stubs (verified via AST/import scan):
#   - fastmcp            : FastMCP, JWTVerifier, FastMCPProxy, ProxyClient
#   - fastapi            : Header, HTTPException, status (mcp_stub_auth)
#   - uvicorn[standard]  : CMD entrypoint
#   - pyjwt              : JWTVerifier (fastmcp.server.auth.providers.jwt)
#
# Transitive (installed automatically):
#   - mcp       (from fastmcp)
#   - starlette (from fastapi)
#   - httpx     (from fastmcp)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastmcp==4.0.0" \
        "fastapi==0.141.1" \
        "uvicorn[standard]==0.53.0" \
        "pyjwt==2.15.0" \
    && groupadd --system --gid 999 mcp \
    && useradd --system --uid 999 --gid mcp \
        --home-dir /app --shell /usr/sbin/nologin mcp

# Package layout mirrors the repo (and dev-up): `mcp_servers` is imported as
# a package, sibling imports are absolute (`from mcp_servers.mcp_stub_runtime
# import ...`), and `/app` stays free of a top-level `platform/` dir that
# would shadow the stdlib module.
COPY --chown=mcp:mcp mcp_servers/*.py /app/mcp_servers/
COPY --chown=mcp:mcp mcp_servers/${MCP_NAME}/ /app/mcp_servers/${MCP_NAME}/

# Domain schema SoT only — stubs need ONLY external_schemas.py and
# platform_schemas.py. Other files in domain/mcp/ (models, tool_policy,
# api_redaction, argument_policy) are not imported by stubs and stay out.
COPY --chown=mcp:mcp src/palatium_ai/__init__.py /app/src/palatium_ai/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/__init__.py /app/src/palatium_ai/domain/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/__init__.py /app/src/palatium_ai/domain/mcp/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/external_schemas.py \
    /app/src/palatium_ai/domain/mcp/external_schemas.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/platform_schemas.py \
    /app/src/palatium_ai/domain/mcp/platform_schemas.py

USER mcp

EXPOSE 8080 8081 8082 8090 8091

# Health check: single-quoted shell string so inner double quotes need no escape.
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c 'import os,urllib.request; p=os.environ.get("MCP_PORT","8080"); urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=2)'

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn ${MCP_MODULE}:app --host 0.0.0.0 --port ${MCP_PORT}"]