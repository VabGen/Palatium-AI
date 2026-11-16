/**
 * Presentation skin for recommendation sections (Kimi cream tip card).
 *
 * Contract signal — not a phrase list (055): Formatter emits recommendation
 * sections with ``icon: "check"`` (schema allow-list / prompts). OpenAI structured
 * outputs + Anthropic typed blocks + Kimi Messages content blocks all prefer typed
 * fields over title-string matching.
 */

import type { IconToken } from '../types/contentDocument';

/** True when the block carries the recommendation chrome token. */
export function isRecommendationChrome(icon: IconToken | null | undefined): boolean {
  return icon === 'check';
}
