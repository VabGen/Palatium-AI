/**
 * Big Tech transcript rewind helpers (ChatGPT / Claude / Kimi).
 *
 * Edit  — drop the edited user turn and everything after it.
 * Regenerate — drop the assistant answer and the tail; keep the prompting user
 *              turn in the UI, but truncate the server *before* that user turn so
 *              ``processIntent`` can append user+assistant again without duplicates.
 */

export type RewindableChatMessage = {
  id: string;
  role: 'user' | 'assistant' | string;
};

export function messagesKeptBeforeEdit<T extends RewindableChatMessage>(
  messages: readonly T[],
  userMessageId: string
): T[] {
  const index = messages.findIndex(msg => msg.id === userMessageId && msg.role === 'user');
  if (index < 0) return [...messages];
  return messages.slice(0, index);
}

/** Persisted turns to keep when editing a user message. */
export function keepCountBeforeEdit<T extends RewindableChatMessage>(
  messages: readonly T[],
  userMessageId: string
): number {
  return messagesKeptBeforeEdit(messages, userMessageId).length;
}

/**
 * UI prefix for regenerate: everything up to and including the prompting user turn.
 * Assistant being regenerated and later turns are dropped.
 */
export function messagesKeptForRegenerate<T extends RewindableChatMessage>(
  messages: readonly T[],
  assistantMessageId: string
): { kept: T[]; userMessage: T | null; assistantIndex: number } {
  const assistantIndex = messages.findIndex(
    msg => msg.id === assistantMessageId && msg.role === 'assistant'
  );
  if (assistantIndex < 0) {
    return { kept: [...messages], userMessage: null, assistantIndex: -1 };
  }
  let userIndex = -1;
  for (let i = assistantIndex - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === 'user') {
      userIndex = i;
      break;
    }
  }
  if (userIndex < 0) {
    return { kept: [...messages], userMessage: null, assistantIndex };
  }
  return {
    kept: messages.slice(0, assistantIndex),
    userMessage: messages[userIndex] ?? null,
    assistantIndex,
  };
}

/**
 * Server keep count for regenerate: turns *before* the prompting user message.
 * ``processIntent`` re-appends that user turn.
 */
export function keepCountBeforeRegenerate<T extends RewindableChatMessage>(
  messages: readonly T[],
  assistantMessageId: string
): number {
  const assistantIndex = messages.findIndex(
    msg => msg.id === assistantMessageId && msg.role === 'assistant'
  );
  if (assistantIndex < 0) return messages.length;
  for (let i = assistantIndex - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === 'user') {
      return i;
    }
  }
  return messages.length;
}
