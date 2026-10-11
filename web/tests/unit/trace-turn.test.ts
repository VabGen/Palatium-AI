import { beforeEach, describe, expect, it } from 'vitest';

import { beginTurnTraceId, getOrCreateTraceId } from '../../src/lib/trace';

describe('turn-scoped trace id', () => {
  beforeEach(() => {
    // Force a known session id, then rotate for turns.
    beginTurnTraceId();
  });

  it('beginTurnTraceId mints a distinct id each call', () => {
    const a = beginTurnTraceId();
    const b = beginTurnTraceId();
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(b).toMatch(/^[0-9a-f]{32}$/);
    expect(a).not.toBe(b);
  });

  it('getOrCreateTraceId reuses the current turn id', () => {
    const turn = beginTurnTraceId();
    expect(getOrCreateTraceId()).toBe(turn);
    expect(getOrCreateTraceId()).toBe(turn);
  });
});
