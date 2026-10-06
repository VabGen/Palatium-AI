/**
 * Адреса Palatium-AI — ЕДИНСТВЕННАЯ точка их вычисления (W9).
 *
 * Раньше REST и WebSocket считали адрес по-разному: `client.ts` читал
 * `VITE_API_BASE_URL`, а сокет жёстко шёл на `window.location.host`. Пока база
 * относительная (штатная схема — reverse proxy на origin СЭД), это совпадало по
 * случайности, и первая же абсолютная база развела бы их: REST ушёл бы на
 * Palatium-AI, а сокет — на СЭД. Такая рассинхронизация видна не сразу (сокет
 * возит только подписку на тред и ping), поэтому она чинится здесь, а не «когда
 * заметим»: обе схемы выводятся из одного значения.
 *
 * Топология задаётся ОДНИМ рычагом — `VITE_API_BASE_URL` (см. §9.1
 * `docs/embedded-assistant.md`):
 *  - не задан → относительная база: `/api/...` и `ws(s)://<origin СЭД>/ws/...`,
 *    то есть СЭД проксирует оба пути к Palatium-AI. CORS не нужен.
 *  - задан абсолютным (`https://palatium.example/api`) → CORS и WSS-allowlist,
 *    оба пути идут на указанный origin; префикс WS выводится из префикса API.
 */
import { ASSISTANT_API_PATH, ASSISTANT_WS_PATH } from '@palatium/contract';

/** Куда идёт REST. Относительный путь (`/api`) — штатный случай. */
export function resolveApiBase(rawBase: string): string {
  const trimmed = rawBase.trim();
  return trimmed.length > 0 ? trimmed.replace(/\/+$/, '') : ASSISTANT_API_PATH;
}

/**
 * Полный URL запроса API.
 *
 * Абсолютный `input` возвращается как есть: так вызываются presigned-адреса
 * объектного хранилища, которые к нашему origin отношения не имеют.
 */
export function resolveApiUrl(rawBase: string, input: string): string {
  if (/^https?:\/\//i.test(input)) return input;
  return `${resolveApiBase(rawBase)}${input}`;
}

/** Префикс WS-пути: из `/prefix/api` получается `/prefix`, из `/api` — пусто. */
function wsPathPrefix(apiPath: string): string {
  const suffix = `/${ASSISTANT_API_PATH.replace(/^\//, '')}`;
  const path = apiPath.replace(/\/+$/, '');
  return path.endsWith(suffix) ? path.slice(0, -suffix.length) : path;
}

/**
 * URL сокета сессии, выведенный из ТОЙ ЖЕ базы, что и REST.
 *
 * `origin` передаётся аргументом (а не читается из `window`), чтобы правило было
 * чистым и проверяемым без браузера: абсолютная база → её origin и `ws`/`wss` по
 * её схеме; относительная → origin страницы.
 */
export function resolveSessionSocketUrl(
  rawBase: string,
  origin: string,
  threadId: string,
  token: string
): string {
  const base = resolveApiBase(rawBase);
  const target = new URL(base, origin);

  // Абсолютная база определяет и схему сокета: `https` → `wss`. Иначе браузер
  // заблокировал бы `ws://` со страницы по HTTPS (mixed content).
  const scheme = target.protocol === 'https:' ? 'wss:' : 'ws:';
  const prefix = wsPathPrefix(target.pathname);
  const path = `${prefix}${ASSISTANT_WS_PATH}/${encodeURIComponent(threadId)}`;
  return `${scheme}//${target.host}${path}?token=${encodeURIComponent(token)}`;
}

/** База сборки: пустая строка → относительные пути (штатная схема СЭД). */
export const API_BASE_RAW: string = import.meta.env.VITE_API_BASE_URL ?? '';

export function apiUrl(input: string): string {
  return resolveApiUrl(API_BASE_RAW, input);
}

export function sessionSocketUrl(threadId: string, token: string): string {
  return resolveSessionSocketUrl(API_BASE_RAW, window.location.origin, threadId, token);
}
