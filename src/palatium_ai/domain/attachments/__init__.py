# src/palatium_ai/domain/attachments/__init__.py

"""Attachment contracts: aggregate, axis types, policies and derived content (000, 020)."""

from .content import AttachmentContent, AttachmentScanSummary
from .context import AttachmentContextBlock, AttachmentTurnContext
from .errors import (
    AttachmentContentMissingError,
    AttachmentError,
    AttachmentIntakeRejectedError,
    AttachmentModeMismatchError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentUploadTooLargeError,
)
from .indexing import AttachmentIndexPayload
from .models import Attachment
from .policies import (
    DEFAULT_ATTACHMENT_LIMITS,
    SUPPORTED_MEDIA_TYPES,
    AttachmentIntakePolicy,
    AttachmentLimits,
    AttachmentRetentionPolicy,
    IntakeDecision,
)
from .types import AttachmentMode, AttachmentRejectionReason, AttachmentStatus

__all__ = [
    "DEFAULT_ATTACHMENT_LIMITS",
    "SUPPORTED_MEDIA_TYPES",
    "Attachment",
    "AttachmentContent",
    "AttachmentContentMissingError",
    "AttachmentContextBlock",
    "AttachmentError",
    "AttachmentIndexPayload",
    "AttachmentIntakePolicy",
    "AttachmentIntakeRejectedError",
    "AttachmentLimits",
    "AttachmentMode",
    "AttachmentModeMismatchError",
    "AttachmentNotFoundError",
    "AttachmentNotUsableError",
    "AttachmentRejectionReason",
    "AttachmentRetentionPolicy",
    "AttachmentScanSummary",
    "AttachmentStatus",
    "AttachmentTurnContext",
    "AttachmentUploadTooLargeError",
    "IntakeDecision",
]
