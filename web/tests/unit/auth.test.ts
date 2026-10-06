import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SED_EVENTS } from '@palatium/contract';

import {
  getAuthToken,
  requestHostTokenRefresh,
  setAuthToken,
  setRuntimeMode,
} from '../../src/runtime/auth';

/**
 * Auth-состояние (084, план §2.5/§4.1).
 *
 * Это не «тест геттера»: требование «токен живёт только в памяти» проверяется
 * только так — попыткой найти его в storage/cookie после записи. E2E этого не
 * покажет: там токен и не должен появляться в storage, а отличить «не пишем» от
 * «пишем и быстро чистим» можно лишь на уровне модуля.
 */

function requestedEvents(): CustomEvent[] {
  const seen: CustomEvent[] = [];
  const listener = (event: Event): void => {
    seen.push(event as CustomEvent);
  };
  window.addEventListener(SED_EVENTS.TOKEN_REQUESTED, listener);
  // Слушатель снимается тестом, а не остаётся висеть между тестами (080: без cleanup
  // подписки текут и влияют на порядок прогона).
  afterEach(() => window.removeEventListener(SED_EVENTS.TOKEN_REQUESTED, listener));
  return seen;
}

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken(null);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('token storage', () => {
  it('keeps the token in memory and never in localStorage / sessionStorage / cookie', () => {
    setAuthToken('tok-1');

    expect(getAuthToken()).toBe('tok-1');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
  });

  it.each([null, '', '   '])('clears the token for %j', value => {
    setAuthToken('tok-1');
    setAuthToken(value);

    expect(getAuthToken()).toBeNull();
  });
});

describe('host refresh', () => {
  it('refuses to refresh in standalone mode — there the host does not exist', async () => {
    await expect(requestHostTokenRefresh()).rejects.toThrow(/host mode/i);
  });

  it('asks the host exactly once for parallel callers', async () => {
    setRuntimeMode('host');
    const events = requestedEvents();

    const first = requestHostTokenRefresh();
    const second = requestHostTokenRefresh();
    setAuthToken('tok-2');

    await expect(first).resolves.toBe('tok-2');
    await expect(second).resolves.toBe('tok-2');
    // Шторм 401 породил бы шторм событий и столько же обращений к СЭД.
    expect(events).toHaveLength(1);
  });

  it('issues a new request after the previous one settled', async () => {
    setRuntimeMode('host');
    const events = requestedEvents();

    const first = requestHostTokenRefresh();
    setAuthToken('tok-2');
    await first;
    const second = requestHostTokenRefresh();

    expect(events).toHaveLength(2);
    setAuthToken('tok-3');
    await expect(second).resolves.toBe('tok-3');
  });

  it('rejects after the timeout instead of waiting forever for the host', async () => {
    vi.useFakeTimers();
    setRuntimeMode('host');
    requestedEvents();

    const pending = requestHostTokenRefresh();
    const rejection = expect(pending).rejects.toThrow(/Host/);
    await vi.advanceTimersByTimeAsync(5_000);
    await rejection;

    // Просроченный запрос не остаётся «в полёте»: следующий вызов — это НОВОЕ
    // обращение к host, а не возврат того же отклонённого промиса.
    const refreshed = requestHostTokenRefresh();
    setAuthToken('tok-2');

    await expect(refreshed).resolves.toBe('tok-2');
  });

  it('does not treat a blank token from the context as a refreshed token', async () => {
    vi.useFakeTimers();
    setRuntimeMode('host');
    requestedEvents();

    let settled = false;
    const pending = requestHostTokenRefresh().then(value => {
      settled = true;
      return value;
    });

    // Пустой/пробельный токен — это «контекст без токена», а не обновление:
    // разрешить им ожидание значило бы отдать клиенту пустой Bearer.
    setAuthToken('   ');
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);

    setAuthToken('tok-2');

    await expect(pending).resolves.toBe('tok-2');
  });
});
