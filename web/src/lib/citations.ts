/**
 * Citation anchors → то, что можно показать (W3b, 055).
 *
 * Модель (`domain/content/citations/models.py`) несёт ДВА разных координатных
 * пространства, и клиент не имеет права их смешивать:
 *
 *  - `answer_range` — смещение внутри текста, который аннотировал провайдер (сырой
 *    ответ LLM). После `schema_first` ответ пересобран в блоки, поэтому это
 *    смещение НЕ адресует ничего в отрисованном документе — подсвечивать по нему
 *    значило бы подсветить случайный символ;
 *  - `source_range` / `page` — место в ИСТОЧНИКЕ. Точную подсветку можно сделать
 *    только по тексту источника, которого у клиента пока нет (это следующий шаг
 *    W3b: серверный слайс + проверка среза по `quote`).
 *
 * Поэтому здесь нет «умного» угадывания позиции: функция отдаёт ровно ту
 * информацию о месте, которую дал провайдер, а `none` — честное «неизвестно»
 * (никогда не 0 и не «начало документа»).
 */
import type { CitationRef } from '../types/contentDocument';

/** Одна карточка-источник: citations одного `source_ref` в порядке документа. */
export type CitationGroup = {
  sourceRef: string;
  /** Только http(s): `javascript:`/`data:` из ответа модели не станут ссылкой (020). */
  href: string | null;
  citations: CitationRef[];
};

/** Где провайдер расположил цитату; `none` — он этого не сказал. */
export type CitationPosition =
  { kind: 'page'; page: number } | { kind: 'chars'; start: number; end: number } | { kind: 'none' };

const HTTP_PROTOCOLS = new Set(['http:', 'https:']);

/**
 * Безопасный href для источника или `null`.
 *
 * `source_ref` приходит от провайдера/модели, то есть является недоверенным
 * вводом: `javascript:` в `href` — исполнение кода по клику. Пропускаем только
 * http(s) и только абсолютный URL; имя файла ссылкой не становится.
 */
export function safeSourceHref(sourceRef: string): string | null {
  const raw = sourceRef.trim();
  if (!raw || !/^https?:\/\//i.test(raw)) return null;
  try {
    const url = new URL(raw);
    return HTTP_PROTOCOLS.has(url.protocol) ? url.toString() : null;
  } catch {
    return null;
  }
}

/** Позиция цитаты в источнике — без домыслов и без clamp. */
export function citationPosition(citation: CitationRef): CitationPosition {
  if (typeof citation.page === 'number' && citation.page >= 1) {
    return { kind: 'page', page: citation.page };
  }
  const span = citation.source_range;
  if (span && span[1] > span[0]) {
    return { kind: 'chars', start: span[0], end: span[1] };
  }
  return { kind: 'none' };
}

/**
 * Ключ для React и для дедупликации.
 *
 * Бэкенд уже дедуплицирует по `(anchor, source_ref, answer_range)`, но клиент
 * получает и сохранённые документы: дубль в одном ответе — это две одинаковые
 * карточки в панели, то есть шум, а не информация.
 */
export function citationKey(citation: CitationRef): string {
  const span = citation.source_range;
  return [
    citation.anchor,
    citation.source_ref,
    citation.quote ?? '',
    citation.page ?? '',
    span ? `${span[0]}-${span[1]}` : '',
  ].join('|');
}

/**
 * Сгруппировать цитаты по источнику, сохранив порядок первого появления.
 *
 * Группировка нужна потому, что в ответе один документ цитируется несколько раз:
 * пять одинаковых чипов «Договор.pdf» — это не пять источников.
 */
export function groupCitations(citations: readonly CitationRef[]): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  const seen = new Set<string>();
  for (const citation of citations) {
    const key = citationKey(citation);
    if (seen.has(key)) continue;
    seen.add(key);
    const existing = groups.get(citation.source_ref);
    if (existing) {
      existing.citations.push(citation);
      continue;
    }
    groups.set(citation.source_ref, {
      sourceRef: citation.source_ref,
      href: safeSourceHref(citation.source_ref),
      citations: [citation],
    });
  }
  return [...groups.values()];
}
