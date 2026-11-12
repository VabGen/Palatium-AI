import { afterEach, describe, expect, it } from 'vitest';
import {
  getRuntimeSnapshot,
  markStandalone,
  startNewThread,
  switchThread,
} from '../../src/runtime/store';

describe('P1b switchThread', () => {
  afterEach(() => {
    startNewThread();
  });

  it('adopts a durable thread id and clears host ownership flag', () => {
    markStandalone();
    switchThread('thread-durable-1');
    const snap = getRuntimeSnapshot();
    expect(snap.threadId).toBe('thread-durable-1');
    expect(snap.threadFromHost).toBe(false);
  });

  it('ignores invalid ids', () => {
    markStandalone();
    const before = getRuntimeSnapshot().threadId;
    switchThread('   ');
    expect(getRuntimeSnapshot().threadId).toBe(before);
  });
});
