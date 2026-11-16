import type { ComposerMode } from '../components/ComposerModePills';

/**
 * Pills win over model dropdown. Model `k2-think` / `k2-agent` map when no pill.
 */
export function resolveEffectiveComposerMode(
  pill: ComposerMode | null,
  modelId: string
): ComposerMode | null {
  if (pill) return pill;
  if (modelId === 'k2-think') return 'deep_think';
  if (modelId === 'k2-agent') return 'agent';
  return null;
}
