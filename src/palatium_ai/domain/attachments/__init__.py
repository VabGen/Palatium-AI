# src/palatium_ai/domain/attachments/__init__.py

"""Attachment contracts: aggregate, axis types, policies and derived content (000, 020)."""

from .content import AttachmentContent, AttachmentScanSummary
from .context import AttachmentContextBlock, AttachmentTurnContext
from .errors import (
    AttachmentChunkedUploadError,
    AttachmentConnectorUnavailableError,
    AttachmentContentMissingError,
    AttachmentError,
    AttachmentIntakeRejectedError,
    AttachmentModeMismatchError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentRestoreNotAllowedError,
    AttachmentTooLargeError,
    AttachmentUploadTooLargeError,
)
from .indexing import (
    AttachmentAnalyzePayload,
    AttachmentIndexPayload,
    AttachmentProjectRef,
    AttachmentRestorePayload,
)
from .models import Attachment
from .parse_routing import (
    AUTO_ATTACH_CHARS,
    DEFAULT_MIN_AVG_CHARS_PER_PAGE,
    INTENT_TEXT_LIMIT,
    ExtractionSource,
    ParseRouteDecision,
    ParseStrategy,
    TextFromChatDecision,
    TextFromChatRoute,
    choose_parse_strategy,
    route_text_from_chat,
    text_layer_is_sufficient,
)
from .policies import (
    DEFAULT_ATTACHMENT_LIMITS,
    SUPPORTED_MEDIA_TYPES,
    AttachmentIntakePolicy,
    AttachmentLimits,
    AttachmentRetentionPolicy,
    IntakeDecision,
)
from .read import (
    DEFAULT_READ_MAX_CHARS,
    AttachmentReadRequest,
    AttachmentReadResult,
    ExtractStatus,
    OcrEngine,
    extraction_source_to_extract_status,
    extraction_source_to_ocr_engine,
)
from .types import (
    AttachmentExtractStatus,
    AttachmentMode,
    AttachmentRejectionReason,
    AttachmentStatus,
)

__all__ = [
    "AUTO_ATTACH_CHARS",
    "DEFAULT_ATTACHMENT_LIMITS",
    "DEFAULT_MIN_AVG_CHARS_PER_PAGE",
    "DEFAULT_READ_MAX_CHARS",
    "INTENT_TEXT_LIMIT",
    "SUPPORTED_MEDIA_TYPES",
    "Attachment",
    "AttachmentAnalyzePayload",
    "AttachmentChunkedUploadError",
    "AttachmentConnectorUnavailableError",
    "AttachmentContent",
    "AttachmentContentMissingError",
    "AttachmentContextBlock",
    "AttachmentError",
    "AttachmentExtractStatus",
    "AttachmentIndexPayload",
    "AttachmentIntakePolicy",
    "AttachmentIntakeRejectedError",
    "AttachmentLimits",
    "AttachmentMode",
    "AttachmentModeMismatchError",
    "AttachmentNotFoundError",
    "AttachmentNotUsableError",
    "AttachmentProjectRef",
    "AttachmentReadRequest",
    "AttachmentReadResult",
    "AttachmentRejectionReason",
    "AttachmentRestoreNotAllowedError",
    "AttachmentRestorePayload",
    "AttachmentRetentionPolicy",
    "AttachmentScanSummary",
    "AttachmentStatus",
    "AttachmentTooLargeError",
    "AttachmentTurnContext",
    "AttachmentUploadTooLargeError",
    "ExtractStatus",
    "ExtractionSource",
    "IntakeDecision",
    "OcrEngine",
    "ParseRouteDecision",
    "ParseStrategy",
    "TextFromChatDecision",
    "TextFromChatRoute",
    "choose_parse_strategy",
    "extraction_source_to_extract_status",
    "extraction_source_to_ocr_engine",
    "route_text_from_chat",
    "text_layer_is_sufficient",
]
