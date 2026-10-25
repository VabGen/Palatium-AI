/**
 * Место цитаты в тексте источника (W3b-2).
 *
 * Панель показывает ОКНО исходного текста (сервер ограничивает его по размеру) и
 * подсвечивает найденный диапазон. Что здесь принципиально не делается:
 *
 *  - **нет подсветки «на глазок»**: сервер вернул `start`/`end` или ничего. Если он
 *    сказал «цитата встречается дважды» / «не найдена», честный ответ — текст без
 *    подсветки и объяснение, а не подсветка ближайшего похожего места (055);
 *  - **нет собственного поиска по тексту**: клиент не умеет отличать «то же самое»
 *    от «похожего» (нормализация пробелов живёт рядом с матчингом, на сервере);
 *  - **нет докачки файла целиком**: фрагмент — то, что нужно, чтобы поверить цитате;
 *    открыть документ целиком — отдельное действие, а не побочный эффект клика (020).
 *
 * Пометка «текст с редактированием» обязательна: при `masked` пользователь читает
 * отредактированный при приёме файла вид, и молчать об этом — значит выдать его за
 * оригинал.
 */
import { useEffect, useRef, useState, type RefObject } from 'react';

import { locateCitation, type CitationLocateResponse } from '../api/client';
import { t } from '../i18n';
import type { CitationRef } from '../types/contentDocument';

export type SourcePanelProps = {
  citation: CitationRef;
  /** Bound by the server only when the label names exactly one upload. */
  attachmentId: string;
  userId: string;
  orgId: string;
  onClose: () => void;
};

type PanelState =
  { status: 'loading' } | { status: 'ready'; data: CitationLocateResponse } | { status: 'error' };

export function SourcePanel({ citation, attachmentId, userId, orgId, onClose }: SourcePanelProps) {
  const [state, setState] = useState<PanelState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const sectionRef = useRef<HTMLElement | null>(null);
  const markRef = useRef<HTMLElement | null>(null);

  // Один запрос на открытие/повтор. AbortController обязателен: клик по другой
  // цитате или закрытие панели размонтирует компонент, и «догоняющий» ответ не
  // должен писать состояние в уже удалённое дерево (080). Сам переход в loading
  // делает обработчик повтора, а не эффект: setState в теле эффекта запускает
  // каскад рендеров (linter `react-hooks/set-state-in-effect`).
  useEffect(() => {
    const controller = new AbortController();
    locateCitation(
      attachmentId,
      {
        quote: citation.quote ?? '',
        source_range: citation.source_range ?? null,
        anchor: citation.anchor,
      },
      userId,
      orgId,
      controller.signal
    )
      .then(data => {
        if (!controller.signal.aborted) setState({ status: 'ready', data });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: 'error' });
      });
    return () => controller.abort();
  }, [
    attachmentId,
    citation.anchor,
    citation.quote,
    citation.source_range,
    userId,
    orgId,
    attempt,
  ]);

  // Фокус уходит на подсветку: иначе после клика он остаётся на кнопке, а новый
  // текст для скринридера не объявлен. Без подсветки — на саму панель.
  useEffect(() => {
    if (state.status !== 'ready') return;
    const target = markRef.current ?? sectionRef.current;
    target?.focus();
  }, [state]);

  return (
    <section
      className="source-panel"
      aria-label={t('cite.sourcePanel')}
      tabIndex={-1}
      ref={sectionRef}
    >
      <div className="source-panel-head">
        <span className="source-panel-file">{citation.source_ref}</span>
        <button type="button" className="source-panel-close" onClick={onClose}>
          {t('cite.sourceClose')}
        </button>
      </div>

      {state.status === 'loading' && <p className="source-panel-note">{t('cite.sourceLoading')}</p>}

      {state.status === 'error' && (
        <div className="source-panel-error">
          <p className="source-panel-note">{t('cite.sourceError')}</p>
          <button
            type="button"
            className="source-panel-retry"
            onClick={() => {
              setState({ status: 'loading' });
              setAttempt(n => n + 1);
            }}
          >
            {t('cite.sourceRetry')}
          </button>
        </div>
      )}

      {state.status === 'ready' && (
        <>
          {state.data.text_state === 'masked' && (
            <p className="source-panel-note">{t('cite.sourceMasked')}</p>
          )}
          {unavailableReason(state.data) !== null && (
            <p className="source-panel-note">{unavailableReason(state.data)}</p>
          )}
          <RenderedSource data={state.data} markRef={markRef} />
          {(state.data.window_start > 0 || state.data.window_end < state.data.total_chars) && (
            <p className="source-panel-note">{t('cite.sourceTruncated')}</p>
          )}
        </>
      )}
    </section>
  );
}

/** Текст окна с подсветкой ровно того диапазона, который вернул сервер. */
function RenderedSource({
  data,
  markRef,
}: {
  data: CitationLocateResponse;
  markRef: RefObject<HTMLElement | null>;
}) {
  const { text, window_start: windowStart, start, end } = data;
  const localStart = start === null ? null : clamp(start - windowStart, 0, text.length);
  const localEnd = end === null ? null : clamp(end - windowStart, 0, text.length);
  const highlight = localStart !== null && localEnd !== null && localEnd > localStart;

  return (
    <p className="source-panel-text">
      {highlight ? (
        <>
          {text.slice(0, localStart ?? 0)}
          <mark
            ref={node => {
              markRef.current = node;
            }}
            tabIndex={-1}
          >
            {text.slice(localStart ?? 0, localEnd ?? 0)}
          </mark>
          {text.slice(localEnd ?? 0)}
        </>
      ) : (
        text
      )}
    </p>
  );
}

/** Почему подсветки нет — три разных факта, три разных текста (никогда «ничего»). */
function unavailableReason(data: CitationLocateResponse): string | null {
  switch (data.outcome) {
    case 'ambiguous_quote':
      return t('cite.sourceAmbiguous');
    case 'quote_not_found':
      return t('cite.sourceNotFound');
    case 'no_text':
      return t('cite.sourceNoText');
    default:
      return null;
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
