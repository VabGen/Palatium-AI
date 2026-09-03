const TRACE_STORAGE_KEY = 'palatium.trace_id';
export const TRACE_HEADER = 'X-Trace-Id';

export function getOrCreateTraceId(): string {
  try {
    const existing = sessionStorage.getItem(TRACE_STORAGE_KEY);
    if (existing?.trim()) return existing.trim();
    const created = crypto.randomUUID().replace(/-/g, '');
    sessionStorage.setItem(TRACE_STORAGE_KEY, created);
    return created;
  } catch {
    return crypto.randomUUID().replace(/-/g, '');
  }
}

export function adoptTraceIdFromResponse(header: string | null): void {
  const next = header?.trim();
  if (!next) return;
  try {
    sessionStorage.setItem(TRACE_STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
}
