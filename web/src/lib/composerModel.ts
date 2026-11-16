import type { ComposerMode } from '../components/ComposerModePills';

/** UI effort lane («Стандартный / Высокий / Максимальный») → composer_mode. */
export type ReasoningIntensity = 'standard' | 'high' | 'max';

/** Composer context-window preference (client lane; server may clamp later). */
export type ContextLength = 'standard' | 'long' | 'max';

/**
 * Map UI intensity → wire model id used by API today.
 * Product models are server-owned; the composer only exposes effort.
 */
export function resolveWireModelId(intensity: ReasoningIntensity): string {
  if (intensity !== 'standard') return 'k2-think';
  return 'k2';
}

export function resolveComposerModeFromUi(
  intensity: ReasoningIntensity,
  modeIntent: ComposerMode | null
): ComposerMode | null {
  if (modeIntent) return modeIntent;
  if (intensity !== 'standard') return 'deep_think';
  return null;
}

export function contextLengthLabelKey(value: ContextLength): string {
  if (value === 'max') return 'composer.contextLength.max';
  if (value === 'long') return 'composer.contextLength.long';
  return 'composer.contextLength.standard';
}
