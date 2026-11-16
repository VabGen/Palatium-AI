/**
 * Derive kimi.ai history-card snippet + file chips from dialog turns.
 * Snippet = last non-empty assistant prose; files = unique `source_refs` / payload names.
 */
import type { DialogTurnResponse } from '../types/contentDocument';
import {
  attachmentChipMeta,
  attachmentTypeLabel,
  displaySourceRefs,
  isInternalSourceRef,
} from './attachments';

export type HistoryFileChip = {
  filename: string;
  /** kimi.ai meta line — `XLSX 7.78 KB` or `PDF` when size unknown. */
  meta: string;
};

export type HistoryPreview = {
  snippet: string | null;
  files: HistoryFileChip[];
};

/** Collapse markdown noise into a history teaser (≈ two 14/20 lines). */
export function cleanHistorySnippet(raw: string, maxLen = 220): string | null {
  const text = raw
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)]\([^)]*\)/g, '$1')
    .replace(/[*_`~]+/g, '')
    .replace(/\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return null;
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1).trimEnd()}…`;
}

function pushName(out: string[], value: unknown): void {
  if (typeof value !== 'string') return;
  const name = value.trim();
  if (name && !isInternalSourceRef(name)) out.push(name);
}

function refsFromPayload(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return [];
  const out: string[] = [];

  const meta = payload.meta;
  if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
    const refs = (meta as { source_refs?: unknown }).source_refs;
    if (Array.isArray(refs)) {
      const strings = refs.filter((value): value is string => typeof value === 'string');
      displaySourceRefs(strings).forEach(name => out.push(name));
    }
  }

  const document = payload.document;
  if (document && typeof document === 'object' && !Array.isArray(document)) {
    const docMeta = (document as { meta?: unknown }).meta;
    if (docMeta && typeof docMeta === 'object' && !Array.isArray(docMeta)) {
      const refs = (docMeta as { source_refs?: unknown }).source_refs;
      if (Array.isArray(refs)) {
        const strings = refs.filter((value): value is string => typeof value === 'string');
        displaySourceRefs(strings).forEach(name => out.push(name));
      }
    }
  }

  const topRefs = payload.source_refs;
  if (Array.isArray(topRefs)) {
    const strings = topRefs.filter((value): value is string => typeof value === 'string');
    displaySourceRefs(strings).forEach(name => out.push(name));
  }

  const names = payload.attachment_names;
  if (Array.isArray(names)) names.forEach(value => pushName(out, value));

  return out;
}

/** Optional size map from turn payload (`attachments[]` with size_bytes). */
function sizesFromPayload(
  payload: Record<string, unknown> | null | undefined
): Map<string, number> {
  const sizes = new Map<string, number>();
  if (!payload) return sizes;
  const attachments = payload.attachments;
  if (!Array.isArray(attachments)) return sizes;
  for (const item of attachments) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    const name =
      typeof row.filename === 'string'
        ? row.filename.trim()
        : typeof row.name === 'string'
          ? row.name.trim()
          : '';
    const size =
      typeof row.size_bytes === 'number'
        ? row.size_bytes
        : typeof row.size === 'number'
          ? row.size
          : null;
    if (name && size != null && Number.isFinite(size) && size >= 0) {
      sizes.set(name, size);
    }
  }
  return sizes;
}

function chipMeta(filename: string, sizeBytes: number | undefined): string {
  if (sizeBytes != null) return attachmentChipMeta(filename, sizeBytes);
  return attachmentTypeLabel(filename);
}

export function extractHistoryPreview(turns: readonly DialogTurnResponse[]): HistoryPreview {
  let snippet: string | null = null;
  const files: HistoryFileChip[] = [];
  const seen = new Set<string>();
  const sizes = new Map<string, number>();

  for (const turn of turns) {
    if (turn.role === 'assistant') {
      const next = cleanHistorySnippet(turn.content);
      if (next) snippet = next;
    }
    const payload = turn.payload ?? null;
    for (const [name, size] of sizesFromPayload(payload)) {
      sizes.set(name, size);
    }
    for (const filename of refsFromPayload(payload)) {
      if (seen.has(filename)) continue;
      seen.add(filename);
      files.push({ filename, meta: chipMeta(filename, sizes.get(filename)) });
    }
  }

  // Backfill meta if size arrived after the first name sighting.
  for (const file of files) {
    const size = sizes.get(file.filename);
    if (size != null) file.meta = chipMeta(file.filename, size);
  }

  return { snippet, files };
}
