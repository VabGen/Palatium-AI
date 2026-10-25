/**
 * Заметка о том, что ответ — доработка предыдущего (W7b).
 *
 * Показывает ровно те два факта, которые пришли с сервера: сколько блоков изменено и
 * сколько удалено. Само содержимое diff'а не выводится: удалённый блок в текущем
 * документе отсутствует, а реконструировать его на клиенте — снова считать diff там,
 * где его уже посчитали (055). Позиции изменённых блоков приходят индексами, разметку
 * ставит `BlockRenderer`.
 *
 * `role="note"` — не live-регион: заметка читается в порядке документа и не
 * перебивает канал озвучивания стрима (084, W2), который объявляет сам ответ.
 */
import { Pencil } from 'lucide-react';

import { t } from '../i18n';
import type { DocumentRevision } from '../types/contentDocument';

export function RevisionNote({ revision }: { revision?: DocumentRevision | null }) {
  if (!revision) return null;
  const changed = revision.changed_blocks.length;
  const removed = revision.removed_blocks.length;
  // Ни одного изменения — это ре-рендер, а не ревизия; сервер такой diff не присылает.
  if (changed === 0 && removed === 0) return null;

  return (
    <p className="revision-note" role="note">
      <Pencil size={13} aria-hidden />
      <span className="revision-note-title">{t('revision.title')}</span>
      {changed > 0 && (
        <span className="revision-note-count">
          {t('revision.changedCount', { count: changed })}
        </span>
      )}
      {removed > 0 && (
        <span className="revision-note-count">
          {t('revision.removedCount', { count: removed })}
        </span>
      )}
    </p>
  );
}
