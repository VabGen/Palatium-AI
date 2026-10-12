/**
 * @deprecated Prefer ``sanitizeStreamMarkdown`` from ``./markdown``.
 * Kept for existing imports during hotfix 1.1.
 */
import { sanitizeStreamMarkdown } from './markdown';

const HITL_TAG = /<\/?hitl-(?:action|choice)\b[^>]*\/?>/gi;

export function stripHitlTags(markdown: string): string {
  return markdown.replace(HITL_TAG, '').replace(/\n{3,}/g, '\n\n').trim();
}

/** Preview pipeline used by StreamMarkdownPreview. */
export function prepareStreamPreview(markdown: string): string {
  return sanitizeStreamMarkdown(markdown);
}