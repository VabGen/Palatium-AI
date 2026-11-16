import { describe, expect, it } from 'vitest';
import {
  keepCountBeforeEdit,
  keepCountBeforeRegenerate,
  messagesKeptBeforeEdit,
  messagesKeptForRegenerate,
} from '../../src/lib/turnRewind';

describe('turnRewind', () => {
  const thread = [
    { id: 'u1', role: 'user' as const },
    { id: 'a1', role: 'assistant' as const },
    { id: 'u2', role: 'user' as const },
    { id: 'a2', role: 'assistant' as const },
  ];

  it('edit drops the user turn and the tail', () => {
    expect(messagesKeptBeforeEdit(thread, 'u2').map(m => m.id)).toEqual(['u1', 'a1']);
    expect(keepCountBeforeEdit(thread, 'u2')).toBe(2);
  });

  it('regenerate keeps the prompting user turn in the UI', () => {
    const { kept, userMessage } = messagesKeptForRegenerate(thread, 'a2');
    expect(kept.map(m => m.id)).toEqual(['u1', 'a1', 'u2']);
    expect(userMessage?.id).toBe('u2');
    // Server drops the user turn so processIntent can re-append it.
    expect(keepCountBeforeRegenerate(thread, 'a2')).toBe(2);
  });

  it('regenerate mid-thread drops later turns', () => {
    const { kept } = messagesKeptForRegenerate(thread, 'a1');
    expect(kept.map(m => m.id)).toEqual(['u1']);
    expect(keepCountBeforeRegenerate(thread, 'a1')).toBe(0);
  });
});
