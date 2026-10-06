import {
  INTENT_ATTACHMENT_LIMIT,
  completeAttachmentUpload,
  finalizeAttachmentChunks,
  initAttachmentUpload,
  putAttachmentBytes,
  putAttachmentChunk,
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
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png': ['.png'],
  'image/webp': ['.webp'],
  'text/csv': ['.csv'],
  'text/html': ['.html', '.htm'],
  'text/markdown': ['.md'],
  'text/plain': ['.txt', '.log'],
};

/** Mirrors the `ATTACHMENTS_*` defaults; the server enforces the real numbers. */
export const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024;

/**
 * Part size for resumable API uploads (`ATTACHMENTS_MAX_CHUNK_BYTES`, default 8 MiB).
 * Files larger than this go through ``/chunks/{i}`` + finalize instead of a single
 * ``PUT /content`` — reverse proxies and in-memory stores handle parts more reliably.
 */
export const UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024;

/**
 * Paste longer than this becomes a ``text/plain`` attachment chip (mode=attach),
 * not intent ``text``. Aligns with ChatGPT-class auto-convert; the hard chat
 * cap remains ``INTENT_TEXT_LIMIT`` (32_000) in ``api/client.ts``.
 */
export const AUTO_ATTACH_CHARS = 10_000;

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
  /** When set, upload uses ``mode=index`` and scopes knowledge to this project (G09). */
  projectId?: string;
};

/** Tabular files eligible for local ADA HITL analysis (G15). */
export function isTabularAttachmentFilename(filename: string): boolean {
  const lower = filename.toLowerCase();
  return lower.endsWith('.csv') || lower.endsWith('.xlsx') || lower.endsWith('.txt');
}

export type AttachmentDraft = {
  /** Stable client-side key; survives the swap to the server id (no React key churn). */
  localId: string;
  /** Set once the server issued the row; only then can the file enter a turn. */
  serverId?: string;
  filename: string;
  sizeBytes: number;
  /** ``scanning`` = bytes landed, AV/parse in flight; send stays blocked. */
  status: 'uploading' | 'scanning' | 'ready' | 'failed';
  error?: string;
  /** Present when the chip came from a long paste — enables «show in field». */
  sourceText?: string;
  origin?: 'paste' | 'file';
  pageCount?: number | null;
  /** Server intake mode — ``index`` enables project KB HITL. */
  mode?: 'attach' | 'index';
  /** Server pipeline reason when ``status === 'failed'`` (for quarantine restore UX). */
  rejectionReason?: string | null;
  /** HITL restore card already requested for this chip. */
  restoreRequested?: boolean;
  /** Server G06 flag — extracted text looked like PII. */
  containsPii?: boolean;
};

/** Injection quarantine only — manager HITL can re-admit with masked text (W5 G12). */
export function canRequestQuarantineRestore(attachment: AttachmentResponse): boolean {
  return (
    attachment.status === 'quarantined' && attachment.rejection_reason === 'injection_detected'
  );
}

/** Whether clipboard/composer text must leave the intent field and become a file. */
export function shouldAutoAttachText(text: string): boolean {
  return text.length > AUTO_ATTACH_CHARS;
}

/** UTF-8 byte length of ``text`` (attachment size gate uses bytes, not chars). */
export function utf8ByteLength(text: string): number {
  return new TextEncoder().encode(text).byteLength;
}

/** Local date stamp for pasted-text filenames (YYYY-MM-DD, calendar local). */
export function pastedTextDateStamp(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function pastedTextFilename(now: Date = new Date()): string {
  return `pasted-text_${pastedTextDateStamp(now)}.txt`;
}

/**
 * Build a ``text/plain`` File for the existing upload path.
 * Returns ``null`` when empty or over the attachment byte cap (caller toasts).
 */
export function createPastedTextFile(text: string, now: Date = new Date()): File | null {
  if (text.length === 0) return null;
  if (utf8ByteLength(text) > MAX_ATTACHMENT_BYTES) return null;
  return new File([text], pastedTextFilename(now), { type: 'text/plain' });
}

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
    case 'mime_mismatch':
      return t('attach.mimeMismatch');
    case 'active_content':
      return t('attach.activeContent');
    case 'image_too_large':
      return t('attach.imageTooLarge');
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

export type ChunkRange = {
  index: number;
  start: number;
  end: number;
};

/** Byte ranges ``[start, end)`` for a resumable upload; empty when ``sizeBytes <= 0``. */
export function planChunkRanges(
  sizeBytes: number,
  chunkBytes: number = UPLOAD_CHUNK_BYTES
): ChunkRange[] {
  if (sizeBytes <= 0 || chunkBytes <= 0) return [];
  const ranges: ChunkRange[] = [];
  for (let start = 0, index = 0; start < sizeBytes; start += chunkBytes, index += 1) {
    ranges.push({ index, start, end: Math.min(start + chunkBytes, sizeBytes) });
  }
  return ranges;
}

/** True when the API path should stage parts instead of a single ``PUT /content``. */
export function shouldUseChunkedUpload(
  sizeBytes: number,
  chunkBytes: number = UPLOAD_CHUNK_BYTES
): boolean {
  return sizeBytes > chunkBytes;
}

/**
 * Deliver bytes through the API: one ``PUT /content`` for small files, or
 * ``POST /chunks/{i}`` + finalize when larger than ``UPLOAD_CHUNK_BYTES`` (W4 G08).
 */
async function deliverBytesViaApi(
  attachmentId: string,
  file: File,
  mimeType: string,
  target: UploadTarget
): Promise<void> {
  if (!shouldUseChunkedUpload(file.size)) {
    await uploadAttachmentViaApi(attachmentId, file, mimeType, target.userId, target.orgId);
    return;
  }

  const ranges = planChunkRanges(file.size);
  for (const range of ranges) {
    const part = file.slice(range.start, range.end);
    await putAttachmentChunk(attachmentId, range.index, part, target.userId, target.orgId);
  }
  await finalizeAttachmentChunks(attachmentId, ranges.length, target.userId, target.orgId);
}

/**
 * init → PUT → complete, returning the row in its final pipeline state.
 *
 * The PUT transport follows the URL the server handed back: a real `http(s)` URL is
 * a presigned object-store target, while `memory://` marks a store with no HTTP
 * surface of its own (local dev), so the bytes go through the API instead. Both
 * paths end in the same `complete` call, which is what actually scans the file.
 *
 * On the API path, files larger than ``UPLOAD_CHUNK_BYTES`` use resumable chunks
 * (``/chunks/{i}`` + finalize) so reverse proxies never see a single 50 MB body.
 *
 * ``onPhase`` lets the UI flip the chip to ``scanning`` before the long complete
 * round-trip (W1 G04) without inventing a second upload path.
 */
export async function uploadAttachment(
  file: File,
  target: UploadTarget,
  onPhase?: (phase: 'uploading' | 'scanning') => void
): Promise<AttachmentResponse> {
  const mimeType = resolveMimeType(file);
  if (mimeType === null) throw new Error(t('attach.unsupportedType'));

  onPhase?.('uploading');
  const projectId = (target.projectId || '').trim() || undefined;
  const ticket = await initAttachmentUpload(
    {
      thread_id: target.threadId,
      filename: file.name,
      mime_type: mimeType,
      size_bytes: file.size,
      mode: projectId ? 'index' : 'attach',
      project_id: projectId,
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
      await deliverBytesViaApi(ticket.attachment_id, file, mimeType, target);
    }
  } else {
    await deliverBytesViaApi(ticket.attachment_id, file, mimeType, target);
  }

  onPhase?.('scanning');
  return completeAttachmentUpload(ticket.attachment_id, target.userId, target.orgId);
}
