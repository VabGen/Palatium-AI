import { describe, expect, it } from 'vitest';
import { keepCountBeforeEdit, messagesKeptBeforeEdit } from '../../src/lib/editUserTurn';

describe('editUserTurn re-export', () => {
  it('still exposes edit helpers', () => {
    const thread = [
      { id: 'u1', role: 'user' as const },
      { id: 'a1', role: 'assistant' as const },
    ];
    expect(keepCountBeforeEdit(thread, 'u1')).toBe(0);
    expect(messagesKeptBeforeEdit(thread, 'u1')).toEqual([]);
  });
});
