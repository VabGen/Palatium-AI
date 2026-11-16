/**
 * kimi.ai «Закрепить сверху» — UI shelf preference only (not product memory / 060).
 * Durable project membership stays on `session.project_id`.
 */

const PINNED_THREADS_KEY = 'palatium:pinned-threads';

export function readPinnedThreadIds(): string[] {
  try {
    const raw = localStorage.getItem(PINNED_THREADS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === 'string' && id.trim().length > 0);
  } catch {
    return [];
  }
}

export function writePinnedThreadIds(ids: readonly string[]): void {
  try {
    localStorage.setItem(PINNED_THREADS_KEY, JSON.stringify([...ids]));
  } catch {
    // Private mode / quota — preference stays session-scoped via React state.
  }
}

/** Pin moves to front; unpin removes. Returns the next ordered id list. */
export function togglePinnedThreadId(ids: readonly string[], threadId: string): string[] {
  if (ids.includes(threadId)) return ids.filter(id => id !== threadId);
  return [threadId, ...ids.filter(id => id !== threadId)];
}
