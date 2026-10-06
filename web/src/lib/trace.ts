/**
 * Trace-id запроса — ТОЛЬКО в памяти модуля (040 + план §4.1).
 *
 * В storage не пишем: виджет встроен в чужую страницу, и его ключи не должны
 * переживать сессию или делиться между вкладками. Backend всё равно вернёт
 * свой `X-Trace-Id`, и мы продолжим корреляцию уже с ним.
 */
export const TRACE_HEADER = 'X-Trace-Id';

/** Верхняя граница: заголовок приходит извне, отражать его без лимита нельзя (035). */
const MAX_TRACE_ID_LENGTH = 128;

let traceId: string | null = null;

function newTraceId(): string {
  return crypto.randomUUID().replace(/-/g, '');
}

export function getOrCreateTraceId(): string {
  traceId ??= newTraceId();
  return traceId;
}

export function adoptTraceIdFromResponse(header: string | null): void {
  const next = header?.trim();
  if (!next || next.length > MAX_TRACE_ID_LENGTH) return;
  traceId = next;
}
