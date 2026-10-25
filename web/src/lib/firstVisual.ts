/**
 * TTFVF — Time To First Visible Frame одного turn'а (084, W1-клиент).
 *
 * Что измеряется: от синхронного старта `send()` до кадра, в котором браузер уже
 * отрисовал заглушку turn'а (орб фазы + сообщение пользователя). Это
 * единственная величина, за которую отвечает клиент: сервер меряет своё
 * (`palatium_sse_first_block_seconds` — submit → первый `block_delta`), и
 * смешивать их нельзя, иначе непонятно, чья деградация.
 *
 * Почему двойной `requestAnimationFrame`, а не один:
 *
 *  - первый колбэк вызывается ПЕРЕД отрисовкой кадра, в котором React уже
 *    закоммитил DOM (commit → layout → paint). Измерив здесь, мы получили бы
 *    «время до готовности DOM», а не «до видимого кадра» — то есть занижали бы
 *    метрику ровно на время отрисовки, которое и бывает узким местом;
 *  - второй колбэк — уже после paint этого кадра: `performance.now()` в нём
 *    честно стоит после первого видимого изменения.
 *
 * Почему `performance.measure`, а не только возвращаемое значение: метрика
 * обязана иметь потребителя (010). Их два — DevTools Performance (запись видна
 * в таймлайне с именем `palatium:ttfvf`) и E2E-гейт, который читает
 * `performance.getEntriesByName(...)`. В сеть ничего не уходит: в виджете нет и
 * не должно быть RUM-эндпоинта (020 — данные остаются у хоста), поэтому
 * «телеметрия» здесь — запись в таймлайн, а не beacon на чужой сервер.
 *
 * В фоновой вкладке кадров нет (`requestAnimationFrame` не вызывается), значит
 * и записи не будет: turn, отправленный из невидимой вкладки, честно не имеет
 * TTFVF. Это не потеря данных, а свойство метрики — «видимого кадра» не было.
 */
export const TTFVF_MEASURE = 'palatium:ttfvf';

/**
 * Бюджет из плана (W1): «пользователь видит отклик не позже 300 мс». Порог —
 * константа, а не литерал в тесте: иначе гейт и документация разъезжаются.
 */
export const TTFVF_BUDGET_MS = 300;

/**
 * Потолок числа записей в таймлайне. `performance.measure` не переиспользует
 * имена, и без очистки длинная сессия копила бы записи бесконечно (080).
 */
export const MAX_TTFVF_MEASURES = 50;

export type TtfvfSample = {
  /** Сколько прошло от submit до первого видимого кадра, мс. */
  durationMs: number;
  /** Уложились ли в `TTFVF_BUDGET_MS`. Диагностика, а не решение о ретрае. */
  withinBudget: boolean;
};

/** Часы и планировщик вынесены в параметры: без этого метрику не проверить. */
export type FirstVisualOptions = {
  now?: () => number;
  afterPaint?: (run: () => void) => void;
};

function clockNow(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/**
 * Выполнить после отрисовки следующего кадра.
 *
 * Без `requestAnimationFrame` (jsdom, очень старый движок) — микрозадача: кадра
 * не будет вовсе, и «после отрисовки» вырождается в «после текущего тика».
 */
export function afterNextPaint(run: () => void): void {
  if (typeof requestAnimationFrame !== 'function') {
    queueMicrotask(run);
    return;
  }
  requestAnimationFrame(() => requestAnimationFrame(run));
}

/**
 * Начать измерение turn'а. Возвращает отметку времени старта.
 *
 * Вызывать СИНХРОННО в обработчике отправки, до `await` и до `fetch`: иначе в
 * метрику попадёт время ожидания токена/сети, и она перестанет быть клиентской.
 */
export function markFirstVisualStart(now: () => number = clockNow): number {
  return now();
}

/**
 * Дождаться первого видимого кадра и записать измерение.
 *
 * Возвращает промис — юнит-тест проверяет значение, `ChatShell` зовёт
 * fire-and-forget (`void`): метрика не имеет права задерживать или ломать turn.
 * Отсутствие User Timing API не ошибка: `durationMs` в этом случае всё равно
 * посчитан и вернётся вызывающему.
 */
export function measureFirstVisual(
  startedAt: number,
  options: FirstVisualOptions = {}
): Promise<TtfvfSample> {
  const now = options.now ?? clockNow;
  const afterPaint = options.afterPaint ?? afterNextPaint;

  return new Promise<TtfvfSample>(resolve => {
    afterPaint(() => {
      const durationMs = Math.max(0, now() - startedAt);
      recordMeasure(startedAt, durationMs);
      resolve({ durationMs, withinBudget: durationMs <= TTFVF_BUDGET_MS });
    });
  });
}

/**
 * Запись в таймлайн. Best-effort: реализация User Timing в тестовых окружениях
 * неполная (jsdom не знает объектной формы), и ронять из-за диагностики turn
 * нельзя. Ошибка подавляется ТОЛЬКО здесь — это не guard бизнес-логики (035).
 */
function recordMeasure(startedAt: number, durationMs: number): void {
  if (typeof performance === 'undefined') return;
  try {
    const existing = performance.getEntriesByName?.(TTFVF_MEASURE).length ?? 0;
    if (existing >= MAX_TTFVF_MEASURES) performance.clearMeasures?.(TTFVF_MEASURE);
    performance.measure(TTFVF_MEASURE, {
      start: startedAt,
      end: startedAt + durationMs,
      detail: { budgetMs: TTFVF_BUDGET_MS },
    });
  } catch {
    // Таймлайн — диагностика, а не контракт: значение уже посчитано и вернётся.
  }
}
