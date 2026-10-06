# src/palatium_ai/infrastructure/scanning/factory.py

"""MalwareScannerPort factory (070: no unscanned content in non-local environments)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.ports.scanner import MalwareScannerPort
from palatium_ai.infrastructure.scanning.clamav_adapter import ClamAVScanner
from palatium_ai.infrastructure.scanning.noop_scanner import DisabledScanner

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

_NON_LOCAL_ENVIRONMENTS = frozenset({"staging", "production"})


def build_malware_scanner(settings: Settings) -> MalwareScannerPort:
    """Select the AV backend; refuse the disabled scanner outside local/test."""
    config = settings.attachments
    if config.scanner_backend == "clamav":
        logger.info(
            "MalwareScannerPort: ClamAV",
            host=config.clamav_host,
            port=config.clamav_port,
            timeout_seconds=config.clamav_timeout_seconds,
        )
        return ClamAVScanner(
            host=config.clamav_host,
            port=config.clamav_port,
            timeout_seconds=config.clamav_timeout_seconds,
        )

    if settings.app.environment in _NON_LOCAL_ENVIRONMENTS:
        msg = (
            f"ATTACHMENTS_SCANNER_BACKEND=disabled is not allowed in {settings.app.environment!r}: "
            "unscanned uploads would reach the model"
        )
        raise RuntimeError(msg)
    logger.warning(
        "MalwareScannerPort: disabled (dev/test only)",
        environment=settings.app.environment,
    )
    return DisabledScanner()
