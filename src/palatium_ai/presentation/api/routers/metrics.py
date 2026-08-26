# src/palatium_ai/presentation/api/routers/metrics.py

"""Prometheus scrape endpoint (outside /api — no JWT)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Expose in-process Prometheus metrics for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
