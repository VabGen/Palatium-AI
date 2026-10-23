import { describe, expect, it } from 'vitest';
import { t } from '../../src/i18n';
import { DEFAULT_PENDING_PHASE, pendingPhaseForNode } from '../../src/lib/pendingOrb';

/**
 * Фаза ожидания — единственный визуальный сигнал «что делает граф» (подписи
 * нет), поэтому маппинг `hop → режим орба` — контракт, а не украшение: тест
 * держит и семантику режимов, и запас прочности на неизвестном узле.
 */
describe('pendingPhaseForNode', () => {
  it.each([
    ['researcher', 'searching'],
    ['formatter', 'composing'],
    ['critic', 'shaping'],
    ['supervisor', 'weaving'],
    ['parallel_workers', 'connecting'],
    ['coder', 'solving'],
  ])('%s → %s', (node, state) => {
    expect(pendingPhaseForNode(node).state).toBe(state);
  });

  it('falls back to the neutral phase before any hop and for an unknown node', () => {
    expect(pendingPhaseForNode(null)).toEqual(DEFAULT_PENDING_PHASE);
    // Новый узел на бэкенде не должен гасить индикатор в пустой бокс.
    expect(pendingPhaseForNode('node_from_a_newer_backend')).toEqual(DEFAULT_PENDING_PHASE);
  });

  it('returns only phases with a translated label', () => {
    const nodes = [
      'context_enricher_continuation',
      'context_enricher_weaving',
      'intent_classifier',
      'attachment_selection',
      'memory_mutation',
      'supervisor',
      'researcher',
      'coder',
      'analyst',
      'parallel_workers',
      'critic',
      'quality_revision',
      'formatter',
    ];
    for (const node of nodes) {
      const { label } = pendingPhaseForNode(node);
      // `t` вернул бы сам ключ, если бы перевод потерялся.
      expect(t(label), label).not.toBe(label);
    }
  });
});
