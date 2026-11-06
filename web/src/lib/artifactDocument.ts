/**
 * Artifacts panel heuristics (ADR 0006): which ContentDocument deserves a
 * side pane vs staying as a compact inline answer.
 *
 * Thresholds are structural (block kinds / count / length), never phrase lists (055).
 */
import type { ContentBlock, ContentDocument } from '../types/contentDocument';

/** Single-paragraph answers shorter than this stay in the transcript bubble. */
export const ARTIFACT_MIN_PARAGRAPH_CHARS = 320;

const RICH_BLOCK_TYPES = new Set<ContentBlock['type']>([
  'table',
  'chart',
  'widget',
  'list',
  'steps',
  'code',
  'kv',
  'callout',
  'formula',
  'heading',
]);

export function isArtifactWorthy(doc: ContentDocument): boolean {
  if (doc.blocks.length === 0) return false;
  if (doc.blocks.length > 1) return true;
  if (doc.blocks.some(block => RICH_BLOCK_TYPES.has(block.type))) return true;
  if ((doc.meta.citations?.length ?? 0) > 0) return true;
  if (doc.meta.source_refs.length > 0) return true;
  if (doc.actions.length > 0) return true;

  const only = doc.blocks[0];
  if (only.type === 'paragraph') {
    return only.text.trim().length >= ARTIFACT_MIN_PARAGRAPH_CHARS;
  }
  return false;
}

/** One-line preview for the transcript anchor card. */
export function artifactPreviewText(doc: ContentDocument, maxChars = 140): string {
  for (const block of doc.blocks) {
    let raw = '';
    switch (block.type) {
      case 'paragraph':
      case 'heading':
        raw = block.text;
        break;
      case 'callout':
        raw = block.body;
        break;
      case 'list':
        raw = block.items.map(item => item.text).filter(Boolean).join(' · ');
        break;
      case 'steps':
        raw = block.items.map(step => step.title).filter(Boolean).join(' · ');
        break;
      case 'kv':
        raw = block.items.map(item => `${item.label}: ${item.value}`).join(' · ');
        break;
      case 'code':
        raw = block.content;
        break;
      case 'table':
        raw = block.columns.join(' · ');
        break;
      case 'chart':
        raw = block.title?.trim() || block.labels.join(' · ');
        break;
      case 'widget':
        raw = block.title ?? '';
        break;
      default:
        break;
    }
    const trimmed = raw.trim().replace(/\s+/g, ' ');
    if (!trimmed) continue;
    if (trimmed.length <= maxChars) return trimmed;
    return `${trimmed.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
  }
  const title = doc.title?.trim();
  return title || '';
}
