import type { DocumentRevision } from '../types/contentDocument';

/**
 * Ревизия ответа приходит на клиент двумя путями: из payload сохранённого хода
 * (`fetchDialogTurns`) и кадром `result` живого SSE-оборота. Форма одна и та же,
 * проверка тоже — иначе живой оборот и hydrate разошлись бы в трактовке.
 */
export function isDocumentRevision(value: unknown): value is DocumentRevision {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.revision_of === 'string' &&
    Array.isArray(record.changed_blocks) &&
    Array.isArray(record.removed_blocks)
  );
}

/**
 * Позиции блоков, которые нужно подсветить.
 *
 * Индексы приходят с сервера: клиент не пересчитывает content-hash (вторая
 * реализация контракта идентичности разошлась бы молча). Старый payload без
 * индексов даёт пустое множество — заметка покажет счётчики, разметка не соврёт.
 */
export function changedBlockIndices(
  revision: DocumentRevision | null | undefined
): ReadonlySet<number> {
  const raw = revision?.changed_block_indices;
  if (!Array.isArray(raw)) return EMPTY;
  const indices = raw.filter(index => Number.isInteger(index) && index >= 0);
  return indices.length > 0 ? new Set(indices) : EMPTY;
}

const EMPTY: ReadonlySet<number> = new Set<number>();
