/**
 * Точка входа embeddable-виджета: регистрация кастомного элемента
 * `<palatium-assistant>`. Описание контракта элемента — в JSDoc класса ниже.
 */
import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  ASSISTANT_TAG,
  checkTenantConsistency,
  isSedContext,
  SED_EVENTS,
  type SedContext,
  type SedThreadChangedDetail,
} from '@palatium/contract';
import App from './App';
import { t } from './i18n';
import { attachHostBridge, type HostBridge } from './lib/hostContext';
import {
  applyHostContext,
  getRuntimeSnapshot,
  setLangOverride,
  setPanelOpen,
  subscribeRuntime,
} from './runtime/store';
import stylesCss from './styles.css?inline';
import tokensCss from './tokens.css?inline';
import widgetCss from './widget.css?inline';

/**
 * Одна таблица стилей на все экземпляры элемента: `adoptedStyleSheets` позволяет
 * делить её между shadow root'ами, поэтому CSS парсится один раз.
 */
const elementStyles = new CSSStyleSheet();
elementStyles.replaceSync([tokensCss, stylesCss, widgetCss].join('\n'));

/**
 * Объявление готовности элемента (событие `palatium:ready`).
 *
 * Вынесено из класса в свободную функцию намеренно: CEM выводит события из
 * JSDoc-тега `@fires`, а разбор `dispatchEvent` внутри метода добавил бы в
 * манифест безымянную запись, потому что имя события — не строковый литерал.
 */
function announceReady(element: HTMLElement): void {
  element.dispatchEvent(
    new CustomEvent(SED_EVENTS.ASSISTANT_READY, { bubbles: true, composed: true })
  );
}

/**
 * Объявление треда (событие `sed:thread-changed`).
 *
 * Вынесено в свободную функцию по той же причине, что и `announceReady`: CEM
 * выводит события из JSDoc-тега `@fires`, а `dispatchEvent` внутри метода с
 * вычисляемым именем добавил бы в манифест безымянную запись.
 *
 * Контракт односторонний: host сохраняет id у себя и в следующий раз присылает
 * его в `SedContext.threadId`. Ответный контекст на это событие не ждём — иначе
 * получился бы цикл «контекст → тред → контекст».
 */
function announceThreadChanged(element: HTMLElement, threadId: string): void {
  const detail: SedThreadChangedDetail = { threadId };
  element.dispatchEvent(
    new CustomEvent(SED_EVENTS.THREAD_CHANGED, { detail, bubbles: true, composed: true })
  );
}

/**
 * Кастомный элемент `<palatium-assistant>` — точка входа embeddable-виджета.
 *
 * Контракт элемента (план §2.3):
 * - Shadow DOM `open`, стили через `adoptedStyleSheets` (без `<style>`: CSP и производительность);
 * - React-root создаётся ОДИН раз и переживает `disconnectedCallback` — СЭД может
 *   перемещать элемент по DOM, и unmount оставил бы пустой виджет навсегда;
 * - публичный API: `setContext()`, `open()`, `close()` + событие `palatium:ready`;
 * - контекст приходит событиями (см. `lib/hostContext.ts`), а не чтением storage.
 *
 * @customElement palatium-assistant
 * @attr lang — BCP-47 интерфейса и форматирования (перекрывает `localization` из контекста)
 * @attr collapsed — только для чтения: панель свёрнута (зеркало `close()`); не выставлять вручную
 * @fires palatium:ready — элемент апгрейдился и готов принимать контекст
 * @fires sed:thread-changed — виджет ведёт диалог в этом треде: host сохраняет id и возвращает его в `SedContext.threadId` (иначе перезагрузка страницы СЭД стирает диалог)
 * @csspart launcher — кнопка-лончер (видна в свёрнутом состоянии)
 * @csspart shell — корневой контейнер панели
 * @csspart header — шапка с заголовком и действиями
 * @csspart transcript — лента сообщений
 * @csspart composer — блок ввода с вложениями
 * @csspart close — кнопка сворачивания панели
 * @cssprop [--accent=#3dbea0] — акцент; любой токен из `tokens.css` переопределяется на хосте
 */
export class PalatiumAssistantElement extends HTMLElement {
  static get observedAttributes(): string[] {
    return ['lang'];
  }

  #root: Root | null = null;
  readonly #mount: HTMLDivElement;
  #bridge: HostBridge | null = null;
  #unsubscribeRuntime: (() => void) | null = null;
  /** Последний объявленный host'у тред — чтобы не повторять то же событие. */
  #announcedThreadId: string | null = null;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: 'open' });
    shadow.adoptedStyleSheets = [elementStyles];
    this.#mount = document.createElement('div');
    this.#mount.id = 'palatium-root';
    shadow.append(this.#mount);
  }

  connectedCallback(): void {
    this.#applyLang(this.getAttribute('lang'));

    if (this.#root === null) {
      this.#root = createRoot(this.#mount);
      this.#root.render(
        <StrictMode>
          <App />
        </StrictMode>
      );
    }

    // Атрибут `[collapsed]` — зеркало runtime-состояния: он нужен и CSS хоста,
    // и внешнему коду, который хочет узнать, развёрнута ли панель.
    this.#unsubscribeRuntime?.();
    this.#unsubscribeRuntime = subscribeRuntime(() => {
      this.#reflectPanelState();
      this.#reflectThread();
    });
    this.#reflectPanelState();
    this.#reflectThread();

    this.#bridge?.destroy();
    this.#bridge = attachHostBridge({ target: this });
    this.#bridge.requestContext();

    announceReady(this);
  }

  disconnectedCallback(): void {
    // React-root НЕ уничтожаем: элемент могут вернуть в DOM.
    this.#bridge?.destroy();
    this.#bridge = null;
    this.#unsubscribeRuntime?.();
    this.#unsubscribeRuntime = null;
  }

  attributeChangedCallback(name: string, _previous: string | null, next: string | null): void {
    if (name === 'lang') this.#applyLang(next);
  }

  /**
   * Программная передача контекста — альтернатива событию `sed:context-changed`.
   *
   * Бросает `TypeError` на структурно невалидный payload и на противоречивый
   * tenant (`scope.tenantId` ≠ `user.orgId` ≠ claim токена). Здесь исключение, а
   * не «тихий пропуск» как в событии: это вызов из кода host'а, и ошибку
   * интеграции надо показать в момент вызова, а не через 500 мс автономным режимом.
   */
  setContext(context: SedContext): void {
    if (!isSedContext(context)) {
      throw new TypeError(t('error.invalidContext'));
    }
    if (checkTenantConsistency(context) === 'mismatch') {
      throw new TypeError(t('error.tenantMismatch'));
    }
    applyHostContext(context);
  }

  /** Развернуть панель. */
  open(): void {
    setPanelOpen(true);
  }

  /** Свернуть панель (виджет остаётся в DOM, показывается лончер). */
  close(): void {
    setPanelOpen(false);
  }

  #reflectPanelState(): void {
    if (getRuntimeSnapshot().panelOpen) this.removeAttribute('collapsed');
    else this.setAttribute('collapsed', '');
  }

  /**
   * Объявляет host'у тред, когда его создал сам виджет.
   *
   * До конца рукопожатия молчим: если host вот-вот пришлёт свой `threadId`,
   * объявленный id всё равно будет заменён, а host получил бы два разных треда
   * на один запуск. После рукопожатия `hostStatus` уже не `pending`, и порядок
   * однозначен: контекст → (возможно) объявление.
   */
  #reflectThread(): void {
    const snapshot = getRuntimeSnapshot();
    if (snapshot.hostStatus === 'pending') return;
    if (snapshot.threadFromHost) {
      // id пришёл от host'а: он его уже знает, эхо только собьёт его обработчик.
      this.#announcedThreadId = snapshot.threadId;
      return;
    }
    if (snapshot.threadId === this.#announcedThreadId) return;
    this.#announcedThreadId = snapshot.threadId;
    announceThreadChanged(this, snapshot.threadId);
  }

  #applyLang(next: string | null): void {
    const lang = next?.trim() ?? '';
    // `lang` нужен и для a11y (язык фрагмента), и как явный override локали форматирования.
    if (lang && this.getAttribute('lang') !== lang) this.setAttribute('lang', lang);
    setLangOverride(lang || null);
  }
}

if (!customElements.get(ASSISTANT_TAG)) {
  // Тег задан ЛИТЕРАЛОМ намеренно: CEM-анализатор читает `tagName` из этого
  // вызова, поэтому константа дала бы в манифесте `ASSISTANT_TAG` вместо тега.
  // `satisfies typeof ASSISTANT_TAG` оставляет проверку на этапе компиляции:
  // расхождение литерала и контракта — ошибка сборки, а не сюрприз в рантайме.
  customElements.define(
    'palatium-assistant' satisfies typeof ASSISTANT_TAG,
    PalatiumAssistantElement
  );
}
