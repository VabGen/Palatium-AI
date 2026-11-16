/**
 * Artifacts panel heuristics (ADR 0006): which ContentDocument may offer an
 * explicit «Open artifact» affordance. Answers always render inline in the
 * transcript; the side pane opens only on user click (Kimi chat parity) —
 * never auto-open and never replace the bubble with an anchor-only card.
 *
 * Thresholds are structural (block kinds / count / length), never phrase lists (055).
 * Aligned with Anthropic artifacts guidance: substantial self-contained content
 * (layout / dense data / multi-section), not short social prose — even if it
 * spans two paragraph blocks.
 */
import type { ContentBlock, ContentDocument } from '../types/contentDocument';
import { displaySourceRefs } from './attachments';

/** Single-paragraph answers shorter than this stay in the transcript bubble. */
export const ARTIFACT_MIN_PARAGRAPH_CHARS = 320;

/** Dense payload types that warrant a side-pane artifact on their own. */
const DENSE_BLOCK_TYPES = new Set<ContentBlock['type']>([
  'table',
  'chart',
  'widget',
  'code',
  'formula',
  'kv',
  'steps',
]);

/** Support types that need accompanying length / section density. */
const SUPPORT_BLOCK_TYPES = new Set<ContentBlock['type']>(['list', 'callout']);

function totalPlainChars(doc: ContentDocument): number {
  let total = 0;
  for (const block of doc.blocks) {
    switch (block.type) {
      case 'paragraph':
      case 'heading':
        total += block.text.trim().length;
        break;
      case 'callout':
        total += block.body.trim().length;
        break;
      case 'list':
        total += block.items.reduce((sum, item) => sum + item.text.trim().length, 0);
        break;
      case 'steps':
        total += block.items.reduce(
          (sum, step) => sum + step.title.trim().length + step.body.trim().length,
          0
        );
        break;
      case 'kv':
        total += block.items.reduce(
          (sum, item) => sum + item.label.trim().length + item.value.trim().length,
          0
        );
        break;
      case 'code':
        total += block.content.length;
        break;
      default:
        break;
    }
  }
  return total;
}

export function isArtifactWorthy(doc: ContentDocument): boolean {
  if (doc.blocks.length === 0) return false;

  if ((doc.meta.citations?.length ?? 0) > 0) return true;
  // Internal stamps (e.g. ``from memory``) are not file citations — ignore them.
  if (displaySourceRefs(doc.meta.source_refs).length > 0) return true;
  if (doc.actions.length > 0) return true;

  if (doc.blocks.some(block => DENSE_BLOCK_TYPES.has(block.type))) return true;

  const headingCount = doc.blocks.filter(block => block.type === 'heading').length;
  // Multi-section answers (analysis / guide / recipe) — Anthropic «sections» flavor.
  if (headingCount >= 2) return true;

  if (doc.blocks.some(block => SUPPORT_BLOCK_TYPES.has(block.type))) {
    return totalPlainChars(doc) >= ARTIFACT_MIN_PARAGRAPH_CHARS;
  }

  const only = doc.blocks.length === 1 ? doc.blocks[0] : null;
  if (only?.type === 'paragraph') {
    return only.text.trim().length >= ARTIFACT_MIN_PARAGRAPH_CHARS;
  }

  // Two short paragraphs / heading+blurb without dense payload → transcript only
  // (social / ack). ``blocks.length > 1`` alone is not enough (055 / screenshot bug).
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
        raw = block.items
          .map(item => item.text)
          .filter(Boolean)
          .join(' · ');
        break;
      case 'steps':
        raw = block.items
          .map(step => step.title)
          .filter(Boolean)
          .join(' · ');
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
