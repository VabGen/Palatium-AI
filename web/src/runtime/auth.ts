/**
 * Auth-состояние виджета — ТОЛЬКО в памяти модуля.
 *
 * Жёсткое требование безопасности (020, план §2.5): access token никогда не
 * попадает в localStorage / sessionStorage / cookie и не логируется. Модульная
 * переменная переживает ре-рендеры и перемещение элемента по DOM, но исчезает
 * при перезагрузке страницы — это ожидаемо: host выдаёт токен заново.
 */
import { SED_EVENTS } from '@palatium/contract';
import { t } from '../i18n';

/** `host` — виджет внутри СЭД (токен даёт host). `standalone` — отдельная страница/разработка. */
export type RuntimeMode = 'host' | 'standalone';

/** Сколько ждём `sed:auth-token-refreshed` перед отказом. */
const REFRESH_TIMEOUT_MS = 5_000;

let token: string | null = null;
let mode: RuntimeMode = 'standalone';
let pendingRefresh: Promise<string> | null = null;
const waiters = new Set<(value: string) => void>();

export function setRuntimeMode(next: RuntimeMode): void {
  mode = next;
}

export function getRuntimeMode(): RuntimeMode {
  return mode;
}

/**
 * Устанавливает токен в памяти. `null`/пустая строка очищают его.
 * Разбудившиеся ожидающие refresh получают новое значение.
 */
export function setAuthToken(next: string | null): void {
  const normalized = next?.trim() ?? '';
  token = normalized.length > 0 ? normalized : null;
  if (token === null) return;
  const pending = [...waiters];
  waiters.clear();
  for (const resolve of pending) resolve(token);
}

export function getAuthToken(): string | null {
  return token;
}

/**
 * Просит host обновить токен и ждёт `sed:auth-token-refreshed`.
 *
 * Разрешено только в `host`-режиме: в standalone обновление — это mint dev-токена.
 * Параллельные вызовы разделяют один запрос (иначе шторм 401 породит шторм событий).
 */
export function requestHostTokenRefresh(): Promise<string> {
  if (mode !== 'host') {
    return Promise.reject(new Error('Token refresh is only available in host mode'));
  }
  if (pendingRefresh) return pendingRefresh;

  const guarded = new Promise<string>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      waiters.delete(waiter);
      reject(
        new Error(
          `${t('error.hostRefreshTimeout')} (${SED_EVENTS.TOKEN_REFRESHED}, ${REFRESH_TIMEOUT_MS} ms)`
        )
      );
    }, REFRESH_TIMEOUT_MS);

    const waiter = (value: string): void => {
      window.clearTimeout(timer);
      resolve(value);
    };

    waiters.add(waiter);
    window.dispatchEvent(new CustomEvent(SED_EVENTS.TOKEN_REQUESTED));
  }).finally(() => {
    pendingRefresh = null;
  });

  pendingRefresh = guarded;
  return guarded;
}
