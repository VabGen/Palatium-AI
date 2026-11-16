import { describe, expect, it } from 'vitest';
import { resolveEffectiveComposerMode } from '../../src/lib/composerMode';

describe('resolveEffectiveComposerMode', () => {
  it('prefers the active pill over the model dropdown', () => {
    expect(resolveEffectiveComposerMode('web_search', 'k2-think')).toBe('web_search');
  });

  it('maps model dropdown when no pill is active', () => {
    expect(resolveEffectiveComposerMode(null, 'k2-think')).toBe('deep_think');
    expect(resolveEffectiveComposerMode(null, 'k2-agent')).toBe('agent');
    expect(resolveEffectiveComposerMode(null, 'k2')).toBeNull();
  });
});
