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
# Почему Poetry НЕТ в runtime:
#   • меньше attack surface / CVE (pip, poetry, gcc, headers)
#   • меньше размер образа и быстрее pull
#   • immutable runtime: только то, что нужно процессу uvicorn
#   • reproducible: зависимости зафиксированы poetry.lock на этапе builder
#
# Build:
#   docker build -t palatium-ai:local .
#   docker build --target test -t palatium-ai:test .
#   docker build --target devtools -t palatium-ai:devtools .
#
# Run:
#   docker run --rm -p 8000:8000 --env-file env/.env palatium-ai:local
#   docker run --rm -e RUN_MIGRATIONS=1 --env-file env/.env palatium-ai:local
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
# Stage: base — общий Python runtime foundation
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
# Stage: deps — Poetry + lockfile install (кэш BuildKit)
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

COPY pyproject.toml poetry.lock README.md ./

RUN --mount=type=cache,target=/tmp/poetry_cache \
    poetry lock --no-ansi \
    && poetry install --only main --no-ansi --no-root

# ---------------------------------------------------------------------------
# Stage: builder — установка пакета + исходники
# ---------------------------------------------------------------------------
    FROM deps AS builder

    ARG WITH_GRAPHITI=0

    COPY src ./src
    COPY alembic.ini ./
    COPY alembic ./alembic

    RUN --mount=type=cache,target=/tmp/poetry_cache \
        poetry install --only main --no-ansi \
        && if [ "${WITH_GRAPHITI}" = "1" ]; then \
             /app/.venv/bin/pip install --no-cache-dir "graphiti-core>=0.11.0,<1.0.0"; \
           fi \
        && find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
        && find /app/.venv -type f -name "*.pyc" -delete \
        && find /app/.venv -type f -name "*.pyo" -delete

# ---------------------------------------------------------------------------
# Stage: runtime — production image (DEFAULT)
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
COPY --chown=app:app env/.env.example /app/env/.env.example
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
# Stage: test — CI image (runtime + test deps + pytest)
# ---------------------------------------------------------------------------
FROM builder AS test

ENV PATH="/app/.venv/bin:$PATH" \
    POETRY_CACHE_DIR=/tmp/poetry_cache

COPY tests ./tests
COPY tox.ini ./tox.ini

RUN --mount=type=cache,target=/tmp/poetry_cache \
    poetry install --with test --no-ansi

USER root
RUN groupadd --system --gid 999 app 2>/dev/null || true \
    && useradd --system --uid 999 --gid app --home-dir /app --shell /usr/sbin/nologin app 2>/dev/null || true \
    && chown -R app:app /app
USER app

WORKDIR /app
ENTRYPOINT []
CMD ["pytest", "-q", "--tb=short"]

# ---------------------------------------------------------------------------
# Stage: devtools — отладка ВНУТРИ контейнера (Poetry + shell). НЕ для prod.
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
    && rm -rf /var/lib/apt/lists/*\
    && curl -L -o src/palatium_ai/infrastructure/export/fonts/DejaVuSans.ttf \
  https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf
USER app

WORKDIR /app
ENTRYPOINT []
CMD ["bash"]
