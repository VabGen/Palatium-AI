# =============================================================================
# MCP stub / gateway servers — FastMCP Streamable HTTP
# =============================================================================
#
# Stub (from repo root):
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=edms --build-arg MCP_MODULE=edms_mcp_server --build-arg MCP_PORT=8080 \
#     -t palatium-mcp-edms:local .
#
# Gateway (Phase 6; set MCP_GATEWAY_SERVER + MCP_UPSTREAM_URL at runtime):
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=gateway --build-arg MCP_MODULE=gateway_mcp_server --build-arg MCP_PORT=8090 \
#     -t palatium-mcp-gateway:local .
#
# Prefer Compose: docker-compose.yml (api + MCP stubs; profile mcp-gateway optional)
#
# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS runtime

ARG MCP_NAME=edms
ARG MCP_MODULE=edms_mcp_server
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

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastmcp==4.0.0" \
        "uvicorn[standard]>=0.50.0,<0.60.0" \
    && groupadd --system --gid 999 mcp \
    && useradd --system --uid 999 --gid mcp \
        --home-dir /app --shell /usr/sbin/nologin mcp

# Shared stub runtime (auth / FastMCP factory)
COPY --chown=mcp:mcp mcp_servers/mcp_stub_auth.py /app/mcp_stub_auth.py
COPY --chown=mcp:mcp mcp_servers/mcp_stub_tools.py /app/mcp_stub_tools.py
COPY --chown=mcp:mcp mcp_servers/mcp_stub_runtime.py /app/mcp_stub_runtime.py
# Stub package (edms|analytics|platform) or gateway/ (Phase 6 ProxyProvider)
COPY --chown=mcp:mcp mcp_servers/${MCP_NAME}/ /app/

# Domain schema SoT only (no mirrored contract.py) — lean package tree
COPY --chown=mcp:mcp src/palatium_ai/__init__.py /app/src/palatium_ai/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/__init__.py /app/src/palatium_ai/domain/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/__init__.py /app/src/palatium_ai/domain/mcp/__init__.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/external_schemas.py \
    /app/src/palatium_ai/domain/mcp/external_schemas.py
COPY --chown=mcp:mcp src/palatium_ai/domain/mcp/platform_schemas.py \
    /app/src/palatium_ai/domain/mcp/platform_schemas.py

USER mcp

EXPOSE ${MCP_PORT}

HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"MCP_PORT\"]}/health', timeout=2)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn ${MCP_MODULE}:app --host 0.0.0.0 --port ${MCP_PORT}"]
