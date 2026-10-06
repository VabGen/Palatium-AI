/**
 * Мост между страницей СЭД и виджетом.
 *
 * Отвечает только за I/O с host'ом: слушает события контекста/токена и шлёт
 * запросы. Состояние живёт в `runtime/` — мост его не хранит.
 *
 * Гонка, которую решает handshake (план §2.2): СЭД может отправить
 * `sed:context-changed` ДО того, как `customElements.define` апгрейдит элемент —
 * такое событие потеряно бы навсегда. Поэтому виджет сам просит контекст
 * (`sed:assistant-context-requested`) и дополнительно читает
 * `window.__palatiumSedContext`, который host мог выставить до загрузки скрипта.
 */
import toast from 'react-hot-toast';
import {
  checkTenantConsistency,
  isSedContext,
  SED_EVENTS,
  type SedContext,
  type SedTokenRefreshedDetail,
} from '@palatium/contract';
import { t } from '../i18n';
import { setAuthToken } from '../runtime/auth';
import { applyHostContext, markStandalone } from '../runtime/store';

/** Окно ожидания ответа host'а на запрос контекста. */
export const CONTEXT_TIMEOUT_MS = 500;

export interface HostBridgeOptions {
  /** Элемент виджета: host может слать события и на него, а не только на `window`. */
  readonly target: HTMLElement;
  /** Опциональный колбэк: контекст так и не пришёл за `CONTEXT_TIMEOUT_MS`. */
  readonly onNoHost?: () => void;
}

export interface HostBridge {
  /** Просит контекст у host'а; повторный вызов после успеха — no-op. */
  requestContext(): void;
  /** Снимает все подписки. Вызывается при `disconnectedCallback`. */
  destroy(): void;
}

export function attachHostBridge(options: HostBridgeOptions): HostBridge {
  const { target, onNoHost } = options;
  let received = false;
  let timer: number | null = null;
  /** Токен последнего отвергнутого контекста — чтобы не повторять одно сообщение. */
  let rejectedToken: string | null = null;

  const clearTimer = (): void => {
    if (timer === null) return;
    window.clearTimeout(timer);
    timer = null;
  };

  /**
   * Принимает контекст, если он согласован. `false` — контекст отброшен
   * (`checkTenantConsistency` = `mismatch`): host обязан прислать согласованную
   * пару «токен ↔ scope», иначе запросы уйдут в один tenant, а UI покажет другой.
   *
   * Отказ виден человеку, а не «тихо ничего не произошло»: расхождение tenant'ов —
   * дефект интеграции, который иначе выглядел бы как «виджет показывает чужие
   * данные». Сообщение выводится один раз на токен, а не на событие: host вправе
   * слать контекст часто (смена документа, перерисовка layout).
   */
  const acceptContext = (context: SedContext): boolean => {
    if (checkTenantConsistency(context) !== 'mismatch') return true;
    if (rejectedToken !== context.token) {
      rejectedToken = context.token;
      toast.error(t('error.tenantMismatch'));
    }
    return false;
  };

  const onContextChanged = (event: Event): void => {
    const detail = (event as CustomEvent<unknown>).detail;
    if (!isSedContext(detail) || !acceptContext(detail)) return;
    received = true;
    clearTimer();
    applyHostContext(detail);
  };

  const onTokenRefreshed = (event: Event): void => {
    const detail = (event as CustomEvent<SedTokenRefreshedDetail | undefined>).detail;
    const next = detail?.token;
    if (typeof next === 'string') setAuthToken(next);
  };

  // Контекст, выставленный до апгрейда элемента.
  if (isSedContext(window.__palatiumSedContext) && acceptContext(window.__palatiumSedContext)) {
    received = true;
    applyHostContext(window.__palatiumSedContext);
  }

  window.addEventListener(SED_EVENTS.CONTEXT_CHANGED, onContextChanged);
  window.addEventListener(SED_EVENTS.TOKEN_REFRESHED, onTokenRefreshed);
  target.addEventListener(SED_EVENTS.CONTEXT_CHANGED, onContextChanged);
  target.addEventListener(SED_EVENTS.TOKEN_REFRESHED, onTokenRefreshed);

  return {
    requestContext(): void {
      if (received) return;
      window.dispatchEvent(
        new CustomEvent(SED_EVENTS.CONTEXT_REQUESTED, { bubbles: true, composed: true })
      );
      clearTimer();
      timer = window.setTimeout(() => {
        timer = null;
        if (received) return;
        markStandalone();
        onNoHost?.();
      }, CONTEXT_TIMEOUT_MS);
    },
    destroy(): void {
      clearTimer();
      window.removeEventListener(SED_EVENTS.CONTEXT_CHANGED, onContextChanged);
      window.removeEventListener(SED_EVENTS.TOKEN_REFRESHED, onTokenRefreshed);
      target.removeEventListener(SED_EVENTS.CONTEXT_CHANGED, onContextChanged);
      target.removeEventListener(SED_EVENTS.TOKEN_REFRESHED, onTokenRefreshed);
    },
  };
}
