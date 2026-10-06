import {
  INTENT_ATTACHMENT_LIMIT,
  completeAttachmentUpload,
  initAttachmentUpload,
  putAttachmentBytes,
  uploadAttachmentViaApi,
} from '../api/client';
import type { AttachmentResponse } from '../api/client';
import { formatNumber, t } from '../i18n';

/**
 * Browser-side door to the attachment intake API (`docs/runbook.md` §16).
 *
 * The server stays the authority: it re-validates the size cap, the MIME↔extension
 * pair and runs the scan/parse/injection pipeline. Everything here is early feedback
 * so an obviously unusable file never costs a round-trip — never the only check (020).
 */

/** Mirror of `_MEDIA_EXTENSIONS` in `domain/attachments/policies.py`, as a UI filter. */
const MEDIA_EXTENSIONS: Readonly<Record<string, readonly string[]>> = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png': ['.png'],
  'image/webp': ['.webp'],
  'text/csv': ['.csv'],
  'text/markdown': ['.md'],
  'text/plain': ['.txt', '.log'],
};

/** Mirrors the `ATTACHMENTS_*` defaults; the server enforces the real numbers. */
export const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024;

/**
 * Attachment count per turn.
 *
 * Source of truth is `ClassifyIntentRequest.attachment_ids` in
 * `presentation/api/routers/intents.py` (`max_length=5`); it reaches this module
 * through `INTENT_ATTACHMENT_LIMIT` in `api/client.ts`. Editing one file (not
 * three) is the point — the constant lives where the contract is documented.
 */
export const MAX_ATTACHMENTS_PER_TURN = INTENT_ATTACHMENT_LIMIT;

export const MAX_ATTACHMENT_LABEL = '50 MB';

/** `accept` attribute for the file picker: extensions only, since browsers lie about MIME. */
export const ATTACHMENT_ACCEPT = Object.values(MEDIA_EXTENSIONS).flat().join(',');

export type UploadTarget = {
  threadId: string;
  userId: string;
  orgId: string;
};

export type AttachmentDraft = {
  /** Stable client-side key; survives the swap to the server id (no React key churn). */
  localId: string;
  /** Set once the server issued the row; only then can the file enter a turn. */
  serverId?: string;
  filename: string;
  sizeBytes: number;
  status: 'uploading' | 'ready' | 'failed';
  error?: string;
};

export function formatAttachmentSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${formatNumber(sizeBytes)} B`;
  if (sizeBytes < 1024 * 1024) return `${formatNumber(Math.round(sizeBytes / 1024))} KB`;
  // Разделитель дробной части — по локали интерфейса (`1,5 MB` в RU), не `toFixed`.
  return `${formatNumber(sizeBytes / (1024 * 1024), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} MB`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return '';
  return name.slice(dot).toLowerCase();
}

/**
 * Resolve the media type to declare at intake.
 *
 * Browsers report an empty `File.type` for some extensions (`.md`, `.log`) and can
 * report a type that disagrees with the name, so the extension registry is the
 * fallback and a mismatch resolves to `null` (refuse) instead of a doomed request.
 */
export function resolveMimeType(file: File): string | null {
  const declared = (file.type || '').toLowerCase();
  const extension = extensionOf(file.name);
  if (declared && MEDIA_EXTENSIONS[declared]) {
    return MEDIA_EXTENSIONS[declared].includes(extension) ? declared : null;
  }
  const match = Object.entries(MEDIA_EXTENSIONS).find(([, extensions]) =>
    extensions.includes(extension)
  );
  return match?.[0] ?? null;
}

/** Refusal copy for a file that cannot be uploaded at all, or `null` when it may go. */
export function attachmentRefusalReason(file: File): string | null {
  if (file.size <= 0) return t('attach.empty');
  if (file.size > MAX_ATTACHMENT_BYTES) return t('attach.tooLarge', { size: MAX_ATTACHMENT_LABEL });
  if (resolveMimeType(file) === null) return t('attach.unsupportedType');
  return null;
}

/** Reason an attachment never became usable; `null` for a ready/indexed row. */
export function refusalLabel(attachment: AttachmentResponse): string | null {
  if (attachment.status === 'ready' || attachment.status === 'indexed') return null;
  switch (attachment.rejection_reason) {
    case 'size_invalid':
      return t('attach.empty');
    case 'size_exceeded':
      return t('attach.tooLarge', { size: MAX_ATTACHMENT_LABEL });
    case 'mime_not_allowed':
      return t('attach.typeNotAccepted');
    case 'extension_mismatch':
      return t('attach.extensionMismatch');
    case 'filename_invalid':
      return t('attach.filenameInvalid');
    case 'turn_limit_exceeded':
      return t('attach.turnLimit', { count: MAX_ATTACHMENTS_PER_TURN });
    case 'not_uploaded':
      return t('attach.notUploaded');
    case 'malware_detected':
      return t('attach.malware');
    case 'scan_failed':
      return t('attach.scanFailed');
    case 'injection_detected':
      return t('attach.injection');
    case 'parse_failed':
      return t('attach.parseFailed');
    default:
      return t('attach.refused');
  }
}

/**
 * init → PUT → complete, returning the row in its final pipeline state.
 *
 * The PUT transport follows the URL the server handed back: a real `http(s)` URL is
 * a presigned object-store target, while `memory://` marks a store with no HTTP
 * surface of its own (local dev), so the bytes go through the API instead. Both
 * paths end in the same `complete` call, which is what actually scans the file.
 */
export async function uploadAttachment(
  file: File,
  target: UploadTarget
): Promise<AttachmentResponse> {
  const mimeType = resolveMimeType(file);
  if (mimeType === null) throw new Error(t('attach.unsupportedType'));

  const ticket = await initAttachmentUpload(
    {
      thread_id: target.threadId,
      filename: file.name,
      mime_type: mimeType,
      size_bytes: file.size,
      mode: 'attach',
    },
    target.userId,
    target.orgId
  );

  if (/^https?:/i.test(ticket.upload_url)) {
    try {
      await putAttachmentBytes(ticket.upload_url, file, mimeType);
    } catch {
      // The store is not reachable from this browser (off-network S3, wrong public
      // endpoint) or the presign expired. Re-send through the API: same row, same
      // cap, same scan/parse pipeline — a transport fallback, not a relaxed path.
      await uploadAttachmentViaApi(
        ticket.attachment_id,
        file,
        mimeType,
        target.userId,
        target.orgId
      );
    }
  } else {
    await uploadAttachmentViaApi(ticket.attachment_id, file, mimeType, target.userId, target.orgId);
  }

  return completeAttachmentUpload(ticket.attachment_id, target.userId, target.orgId);
}
