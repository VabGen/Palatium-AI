# =============================================================================
# palatium-ai — production-grade multi-stage Dockerfile
# =============================================================================
#
# Targets:
#   runtime   (default) — prod API image: venv only, no Poetry, no compilers
#   builder             — Poetry + build toolchain (intermediate)
#   deps                — cached dependency layer only
#   test                — runtime + pytest (CI)
#   devtools            — runtime + Poetry (отладка в контейнере, НЕ для prod)
#
# NOTE:
#   • mcp_servers/ НЕ входит в этот образ. Это отдельные приложения
#     с собственным Dockerfile (mcp_servers/Dockerfile) и PYTHONPATH=/app.
#   • В pyproject.toml → [tool.poetry].packages только palatium_ai.
#
# Build:
#   docker build -t palatium-ai:local .
#   docker build --target test -t palatium-ai:test .
#   docker build --target devtools -t palatium-ai:devtools .
#
# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14
ARG POETRY_VERSION=2.4.1
ARG UVICORN_WORKERS=1
ARG APP_VERSION=0.1.0
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG WITH_GRAPHITI=0

# ---------------------------------------------------------------------------
# Stage: base
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

ARG PYTHON_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ---------------------------------------------------------------------------
# Stage: deps
# ---------------------------------------------------------------------------
FROM base AS deps

ARG POETRY_VERSION
ENV POETRY_VERSION=${POETRY_VERSION} \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# poetry.lock должен быть в репо и в build context (не в .dockerignore).
COPY pyproject.toml poetry.lock README.md ./

# poetry check --lock — не пересчитывает lock, только валидирует.
# Если lock расходится с pyproject → fail fast (reproducible builds).
RUN --mount=type=cache,target=/tmp/poetry_cache \
    poetry check --lock \
    && poetry install --only main --no-root

# ---------------------------------------------------------------------------
# Stage: builder
# ---------------------------------------------------------------------------
FROM deps AS builder

ARG WITH_GRAPHITI=0

# Только src — mcp_servers идёт через свой Dockerfile (не часть этого образа).
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN --mount=type=cache,target=/tmp/poetry_cache \
    poetry install --only main \
    && if [ "${WITH_GRAPHITI}" = "1" ]; then \
         /app/.venv/bin/pip install --no-cache-dir "graphiti-core>=0.11.0,<1.0.0"; \
       fi \
    && find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /app/.venv -type f -name "*.pyc" -delete \
    && find /app/.venv -type f -name "*.pyo" -delete

# ---------------------------------------------------------------------------
# Stage: runtime (default)
# ---------------------------------------------------------------------------
FROM base AS runtime

ARG APP_VERSION
ARG VCS_REF
ARG BUILD_DATE
ARG UVICORN_WORKERS
ARG PYTHON_VERSION

LABEL org.opencontainers.image.title="palatium-ai" \
      org.opencontainers.image.description="ZeroTrust multi-agent AI platform API" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/your-org/palatium-ai" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="palatium-ai"

ENV PATH="/app/.venv/bin:$PATH" \
    APP_HOME=/app \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=${UVICORN_WORKERS} \
    RUN_MIGRATIONS=0 \
    TINI_SUBREAPER=1

RUN groupadd --system --gid 999 app \
    && useradd --system --uid 999 --gid app \
        --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/tmp \
    && chown -R app:app /app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --chown=app:app scripts/docker-entrypoint.sh /app/scripts/docker-entrypoint.sh

RUN sed -i 's/\r$//' /app/scripts/docker-entrypoint.sh \
    && chmod 0555 /app/scripts/docker-entrypoint.sh \
    && chmod -R a-w /app/.venv /app/src /app/alembic /app/alembic.ini \
    && chmod u+w /app/logs /app/tmp

USER app
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.environ.get('UVICORN_PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)"

ENTRYPOINT ["/usr/bin/tini", "--", "sh", "/app/scripts/docker-entrypoint.sh"]
CMD ["uvicorn"]

# ---------------------------------------------------------------------------
# Stage: test
# ---------------------------------------------------------------------------
FROM builder AS test

ENV PATH="/app/.venv/bin:$PATH" \
    POETRY_CACHE_DIR=/tmp/poetry_cache

COPY tests ./tests
COPY tox.ini ./tox.ini

RUN --mount=type=cache,target=/tmp/poetry_cache \
    poetry install --with test

USER root
RUN groupadd --system --gid 999 app 2>/dev/null || true \
    && useradd --system --uid 999 --gid app --home-dir /app --shell /usr/sbin/nologin app 2>/dev/null || true \
    && chown -R app:app /app
USER app

WORKDIR /app
ENTRYPOINT []
CMD ["pytest", "-q", "--tb=short"]

# ---------------------------------------------------------------------------
# Stage: devtools
# ---------------------------------------------------------------------------
FROM builder AS devtools

ENV PATH="/app/.venv/bin:$PATH" \
    POETRY_CACHE_DIR=/tmp/poetry_cache

USER root
RUN groupadd --system --gid 999 app 2>/dev/null || true \
    && useradd --system --uid 999 --gid app --home-dir /app --shell /bin/bash app 2>/dev/null || true \
    && chown -R app:app /app \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*
USER app

WORKDIR /app
ENTRYPOINT []
CMD ["bash"]