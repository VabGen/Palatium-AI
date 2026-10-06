/**
 * Перевод строк (W6) и форматирование под локаль (W11).
 *
 * Модуль намеренно НЕ импортирует `runtime/store` — иначе получился бы цикл
 * (`store → auth → i18n → store`). Локаль сюда ПУШИТ store при изменении, а
 * `t()` остаётся чистой функцией без зависимостей: её можно звать и из React,
 * и из модулей вне дерева (клиент API, вложения, auth).
 *
 * Числа и даты — тоже здесь, а не `toLocaleString()` на месте: иначе формат
 * уезжает на локаль БРАУЗЕРА, и внутри русской страницы СЭД появляется
 * `3:45:12 PM` вместо `15:45:12` (для языка это уже исправлено, для форматов
 * было нет). Один владелец локали — один формат.
 */
import { en, ru, type MessageKey } from './messages';

export type Language = 'ru' | 'en';

export type MessageParams = Readonly<Record<string, string | number>>;

const DICTIONARIES: Record<Language, Record<MessageKey, string>> = { ru, en };

/** Язык → его локаль по умолчанию (регион продукта, не браузера). */
const LANGUAGE_DEFAULT_LOCALE: Record<Language, string> = { ru: 'ru-RU', en: 'en-US' };

/** BCP-47 текущей локали: он же — язык интерфейса и форматов. */
let currentLocale = 'ru-RU';

/** Вызывается из `runtime/store` при каждой публикации состояния. */
export function setI18nLocale(locale: string): void {
  currentLocale = locale;
}

export function getI18nLocale(): string {
  return currentLocale;
}

/** Только `ru`/`en`; всё остальное (например `de-DE`) уходит на `ru` по умолчанию продукта. */
export function resolveLanguage(locale: string): Language {
  return locale.toLowerCase().startsWith('en') ? 'en' : 'ru';
}

/**
 * Локаль для чисел и дат — от РАЗРЕШЁННОГО языка, а не от сырой строки локали.
 *
 * Иначе `de-DE` дал бы русский текст с немецкими разделителями, а `GE` из СЭД
 * (для неё ресурсов нет, `resolveLanguage` → `ru`) — русский текст с форматом
 * браузера. Региональный вариант поддерживаемого языка сохраняем (`en-GB` →
 * `en-GB`): порядок частей даты для него другой, терять это незачем.
 */
function numericLocale(): string {
  const language = resolveLanguage(currentLocale);
  return currentLocale.trim().toLowerCase().startsWith(language)
    ? currentLocale
    : LANGUAGE_DEFAULT_LOCALE[language];
}

/**
 * Число по локали интерфейса.
 *
 * `Intl.NumberFormat` кэшируется браузером, поэтому создание объекта на вызов
 * дешевле, чем выглядит; кэш здесь не нужен (050: кэш без TTL — не кэш).
 */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(numericLocale(), options).format(value);
}

/**
 * Дата/время по локали интерфейса. Значение — ISO-строка с сервера, `Date` или epoch.
 *
 * Неразбираемое значение возвращается КАК ЕСТЬ — видно, что пришло, вместо
 * `Invalid Date` (молчаливая подмена была бы хуже: по ней не отличить баг
 * сервера от бага виджета). Значение без таймзоны трактуется как локальное —
 * контракт API требует `Z` (проверено фикстурами E2E), но падать на чужом
 * ответе виджет не должен.
 */
export function formatDateTime(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { timeStyle: 'medium' }
): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(numericLocale(), options).format(date);
}

function formatParam(value: string | number): string {
  if (typeof value === 'string') return value;
  // Разряды и разделители — по локали, а не `String(n)`: иначе «32000» вместо «32 000».
  return formatNumber(value);
}

/**
 * Перевод по ключу с подстановкой `{param}`.
 *
 * Ключ типизирован, поэтому опечатка или несуществующий ключ — ошибка сборки.
 * Неизвестный параметр остаётся в тексте как есть (видно в UI, не падает).
 */
export function t(key: MessageKey, params?: MessageParams): string {
  const language = resolveLanguage(currentLocale);
  let message = DICTIONARIES[language][key];
  if (!params) return message;

  for (const [name, value] of Object.entries(params)) {
    message = message.split(`{${name}}`).join(formatParam(value));
  }
  return message;
}
