# =============================================================================
# MCP stub servers (edms / analytics) — lightweight FastAPI JSON-RPC stubs
# =============================================================================
#
# Build:
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=edms --build-arg MCP_MODULE=edms_mcp_server --build-arg MCP_PORT=8080 \
#     -t palatium-mcp-edms:local mcp_servers
#
#   docker build -f mcp_servers/Dockerfile \
#     --build-arg MCP_NAME=analytics --build-arg MCP_MODULE=analytics_mcp_server --build-arg MCP_PORT=8081 \
#     -t palatium-mcp-analytics:local mcp_servers
#
# Run:
#   docker run --rm -p 8080:8080 palatium-mcp-edms:local
#
# Prefer Compose: deploy/compose.secrets.example.yml (api + both MCP stubs)
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
    MCP_PORT=${MCP_PORT}

LABEL org.opencontainers.image.title="palatium-mcp-${MCP_NAME}" \
      org.opencontainers.image.description="Palatium AI MCP stub server (${MCP_NAME})" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastapi>=0.140.0,<0.150.0" \
        "uvicorn[standard]>=0.50.0,<0.60.0" \
        "pydantic>=2.13.0,<3.0.0" \
    && groupadd --system --gid 999 mcp \
    && useradd --system --uid 999 --gid mcp \
        --home-dir /app --shell /usr/sbin/nologin mcp

# Копируем shared auth/tools helpers + выбранный stub (edms/ или analytics/)
COPY --chown=mcp:mcp schema_util.py /app/schema_util.py
COPY --chown=mcp:mcp mcp_stub_auth.py /app/mcp_stub_auth.py
COPY --chown=mcp:mcp mcp_stub_tools.py /app/mcp_stub_tools.py
COPY --chown=mcp:mcp ${MCP_NAME}/ /app/

USER mcp

EXPOSE ${MCP_PORT}

HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"MCP_PORT\"]}/health', timeout=2)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn ${MCP_MODULE}:app --host 0.0.0.0 --port ${MCP_PORT}"]
