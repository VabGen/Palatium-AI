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
#   docker build --build-arg WITH_ATTACHMENTS=1 -t palatium-ai:local .  # + minio/pypdf/python-docx
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
ARG WITH_ATTACHMENTS=0

# ---------------------------------------------------------------------------
# Stage: base
# ---------------------------------------------------------------------------
# Pinned by digest, not by the mutable `3.14-slim` tag (025): the tag is a moving target,
# so the code we build on could change without a pull request in this repo. The digest
# below is the multi-arch index of `python:3.14-slim` = 3.14.7-slim-trixie (2026-09-19);
# the tag stays on the line as the human-readable hint. Bumping PYTHON_VERSION without
# refreshing the digest fails the build on purpose (`manifest unknown`) — a silent
# base-image swap is the outcome this pin exists to prevent. Drift is gated by
# `scripts/ci_security.py` (base image pin check).
FROM python:${PYTHON_VERSION}-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS base

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
# LICENSE обязателен: pyproject declares `license-files = ["LICENSE"]`, and the root
# package is built in the *builder* stage — Poetry's backend fails on a declared-but-absent
# license file, which is exactly how the image shipped without `palatium_ai` (see below).
COPY pyproject.toml poetry.lock README.md LICENSE ./

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
ARG WITH_ATTACHMENTS=0

# Только src — mcp_servers идёт через свой Dockerfile (не часть этого образа).
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

# `--only main` keeps the image lean, but the attachment pipeline needs the
# optional `attachments` group (minio / pypdf / python-docx). Without it an
# ATTACHMENTS_BLOB_BACKEND=minio container fails closed on boot, and PDF/DOCX
# parsing raises at request time (see docs/runbook.md §16.2).
#
# The import assertions below are not decoration. `poetry install` builds the root project
# *last*, and its failure used to be swallowed by a trailing `|| true` — the image built
# "successfully" while shipping a venv without `palatium_ai`, and the API died at boot with
# `ModuleNotFoundError: No module named 'palatium_ai'`. Asserting the imports converts that
# into a build failure, which is where it belongs (035: fail fast, never ship a silently
# degraded image). Pinned by tests/unit/test_dockerfile_build_contract.py.
RUN --mount=type=cache,target=/tmp/poetry_cache \
    if [ "${WITH_ATTACHMENTS}" = "1" ]; then \
        poetry install --with attachments \
        && /app/.venv/bin/python -c "import PIL, pytesseract, fitz"; \
    else \
        poetry install --only main; \
    fi \
    && if [ "${WITH_GRAPHITI}" = "1" ]; then \
         /app/.venv/bin/pip install --no-cache-dir "graphiti-core>=0.11.0,<1.0.0" \
         && /app/.venv/bin/python -c "import graphiti_core"; \
       fi \
    && /app/.venv/bin/python -c "import palatium_ai; print('palatium_ai ->', palatium_ai.__file__)"

# Best-effort cleanup, deliberately its own step: a stray __pycache__ must never be able to
# fail the build, and — the other half of the same bug — its `|| true` must never be able to
# hide a failed install by terminating the `&&` chain that precedes it.
RUN find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app/.venv -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage: runtime (default)
# ---------------------------------------------------------------------------
FROM base AS runtime

ARG APP_VERSION
ARG VCS_REF
ARG BUILD_DATE
ARG UVICORN_WORKERS
ARG PYTHON_VERSION
ARG WITH_ATTACHMENTS=0

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
    && chown -R app:app /app \
    && if [ "${WITH_ATTACHMENTS}" = "1" ]; then \
         apt-get update \
         && apt-get install -y --no-install-recommends \
              tesseract-ocr \
              tesseract-ocr-eng \
              tesseract-ocr-rus \
         && rm -rf /var/lib/apt/lists/* \
         && apt-get clean; \
       fi

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/alembic /app/alembic
# Shipped for licence compliance: the image carries MIT code, so it carries the notice
# (OCI `org.opencontainers.image.licenses` above is a label, not the licence text).
COPY --chown=app:app LICENSE /app/LICENSE
COPY --chown=app:app scripts/docker-entrypoint.sh /app/scripts/docker-entrypoint.sh

RUN sed -i 's/\r$//' /app/scripts/docker-entrypoint.sh \
    && chmod 0555 /app/scripts/docker-entrypoint.sh \
    && chmod -R a-w /app/.venv /app/src /app/alembic /app/alembic.ini /app/LICENSE \
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