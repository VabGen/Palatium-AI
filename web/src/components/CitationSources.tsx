/**
 * Источники ответа: сгруппированные чипы + панель цитат + место в источнике (W3b).
 *
 * Что здесь сознательно НЕ делается:
 *
 *  - **нет подсветки в ответе по `answer_range`**: после `schema_first` документ
 *    пересобран из блоков, и смещение в сыром ответе провайдера не адресует
 *    ничего в отрисованном тексте. Подсветить «примерно» — значит подсветить не
 *    то место, а это хуже отсутствия подсветки (040/055);
 *  - **нет кнопки «показать в источнике» без `source_id`**: сервер привязывает id
 *    только когда имя файла однозначно называет одну загрузку. Кнопка, которая
 *    всегда падает, хуже её отсутствия.
 *
 * Что показывается: сам `quote` (дословно, как его передал провайдер), страница
 * или диапазон символов — если провайдер их сообщил — и честное «точное место
 * недоступно», если не сообщил. Для http(s)-источника добавляется ссылка на
 * оригинал. Место в тексте источника открывает `SourcePanel` (W3b-2): сервер
 * отдаёт ограниченное окно текста и абсолютные смещения, клиент их не вычисляет.
 */
import { useEffect, useId, useState } from 'react';

import { t } from '../i18n';
import { citationKey, citationPosition, groupCitations } from '../lib/citations';
import type { CitationRef } from '../types/contentDocument';
import { SourcePanel } from './SourcePanel';

export type CitationSourcesProps = {
  citations: readonly CitationRef[];
  /** Both are needed only when a citation offers "show in source" (W3b-2). */
  userId?: string;
  orgId?: string;
};

export function CitationSources({ citations, userId = '', orgId = '' }: CitationSourcesProps) {
  const groups = groupCitations(citations);
  const [openSource, setOpenSource] = useState<string | null>(null);
  const [located, setLocated] = useState<{ citation: CitationRef; attachmentId: string } | null>(
    null
  );
  const panelId = useId();
  const sourcePanelId = useId();
  const openGroup = groups.find(group => group.sourceRef === openSource) ?? null;

  // Escape закрывает панель источника раньше панели цитат: это вложенный
  // раскрывающийся блок, и «свернуть всё сразу» потеряло бы место, где читатель был.
  // Зависимость — строки, а не найденные группы: группы пересоздаются на каждом рендере.
  useEffect(() => {
    if (openSource === null && located === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (located !== null) {
        setLocated(null);
        return;
      }
      setOpenSource(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [openSource, located]);

  if (groups.length === 0) return null;

  return (
    <div className="citation-sources">
      <ul className="source-ref-chips" aria-label={t('attach.sources')}>
        {groups.map(group => {
          const isOpen = group.sourceRef === openSource;
          return (
            <li key={group.sourceRef} className="source-ref-chip">
              <button
                type="button"
                className={`source-ref-button${isOpen ? ' is-open' : ''}`}
                aria-expanded={isOpen}
                aria-controls={isOpen ? panelId : undefined}
                onClick={() => {
                  setLocated(null);
                  setOpenSource(isOpen ? null : group.sourceRef);
                }}
              >
                <span className="source-ref-name">{group.sourceRef}</span>
                {group.citations.length > 1 && (
                  // Число не склоняется и не читается скринридером отдельно:
                  // доступное имя кнопки — название источника.
                  <span className="source-ref-count" aria-hidden="true">
                    {group.citations.length}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {openGroup !== null && (
        <section className="citation-panel" id={panelId} aria-label={t('cite.panel')}>
          <ol className="citation-list">
            {openGroup.citations.map(citation => (
              <li key={citationKey(citation)} className="citation-item">
                {citation.quote && (
                  <blockquote className="citation-quote">{citation.quote}</blockquote>
                )}
                <p className="citation-meta">{positionLabel(citation)}</p>
                {citation.source_id ? (
                  <button
                    type="button"
                    className="citation-locate"
                    aria-expanded={located?.citation === citation}
                    aria-controls={located?.citation === citation ? sourcePanelId : undefined}
                    // Доступное имя включает начало цитаты: у одного документа их
                    // несколько, и «Показать в источнике» × 5 неразличимы на слух.
                    aria-label={`${t('cite.showInSource')}: ${quotePreview(citation)}`}
                    onClick={() =>
                      setLocated(current =>
                        current?.citation === citation
                          ? null
                          : { citation, attachmentId: citation.source_id ?? '' }
                      )
                    }
                  >
                    {t('cite.showInSource')}
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
          {openGroup.href !== null && (
            <a
              className="citation-link"
              href={openGroup.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('cite.openExternal')}
            </a>
          )}
          {located !== null && (
            <div id={sourcePanelId}>
              <SourcePanel
                key={citationKey(located.citation)}
                citation={located.citation}
                attachmentId={located.attachmentId}
                userId={userId}
                orgId={orgId}
                onClose={() => setLocated(null)}
              />
            </div>
          )}
        </section>
      )}
    </div>
  );
}

/** Короткий превью цитаты для доступного имени кнопки (без разметки и переводов). */
function quotePreview(citation: CitationRef): string {
  const quote = (citation.quote ?? '').trim();
  if (!quote) return citation.source_ref;
  return quote.length > 60 ? `${quote.slice(0, 60)}…` : quote;
}

/** Подпись места цитаты; три состояния позиции — три разных текста, без «0». */
function positionLabel(citation: CitationRef): string {
  const position = citationPosition(citation);
  if (position.kind === 'page') return t('cite.page', { page: String(position.page) });
  if (position.kind === 'chars') {
    return t('cite.chars', { start: String(position.start), end: String(position.end) });
  }
  return t('cite.positionUnavailable');
}
