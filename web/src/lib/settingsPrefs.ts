/**
 * Локальные предпочтения пользователя (страница Settings).
 *
 * Источник истины для аккаунта/подписки — СЭД (host). Здесь только то, что
 * реально принадлежит устройству: тема, уведомления, инструкции чата, промпты.
 * Один ключ localStorage и один тип — иначе настройки разъезжаются по экранам.
 */

export type ThemePreference = 'light' | 'system' | 'dark';

export type VoiceId = 'kimi' | 'warm';

/** `auto` — язык из контекста СЭД/браузера; явный выбор — поверх него. */
export type LanguagePreference = 'auto' | 'en' | 'ru';

export type SavedPrompt = {
  readonly id: string;
  /** Слова-триггеры, по которым промпт подставляется в композер. */
  readonly trigger: string;
  readonly content: string;
};

export type SettingsPrefs = {
  readonly theme: ThemePreference;
  readonly notifications: {
    readonly kimi: boolean;
    readonly reminders: boolean;
    readonly browser: boolean;
  };
  readonly recommendForInput: boolean;
  readonly aiWatermark: boolean;
  readonly learnFromChats: boolean;
  readonly voice: VoiceId;
  readonly language: LanguagePreference;
  readonly preferredName: string;
  readonly occupation: string;
  readonly instructions: string;
  readonly prompts: readonly SavedPrompt[];
};

export const SETTINGS_PREFS_KEY = 'palatium.settings.v1';

export const DEFAULT_SETTINGS_PREFS: SettingsPrefs = {
  theme: 'light',
  notifications: { kimi: true, reminders: true, browser: false },
  recommendForInput: true,
  aiWatermark: false,
  learnFromChats: true,
  voice: 'kimi',
  language: 'auto',
  preferredName: '',
  occupation: '',
  instructions: '',
  prompts: [],
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const bool = (value: unknown, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback;
const text = (value: unknown, fallback: string): string =>
  typeof value === 'string' ? value : fallback;

const isTheme = (value: unknown): value is ThemePreference =>
  value === 'light' || value === 'system' || value === 'dark';

const isVoice = (value: unknown): value is VoiceId => value === 'kimi' || value === 'warm';

const isLanguage = (value: unknown): value is LanguagePreference =>
  value === 'auto' || value === 'en' || value === 'ru';

function readPrompts(value: unknown): readonly SavedPrompt[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(entry => {
    if (!isRecord(entry)) return [];
    const trigger = text(entry.trigger, '').slice(0, 60);
    const content = text(entry.content, '').slice(0, 1500);
    if (!trigger || !content) return [];
    return [{ id: text(entry.id, `p-${trigger}`), trigger, content }];
  });
}

/** Разбор сохранённых настроек: неизвестные/битые поля → дефолт, не падение. */
export function normalizeSettingsPrefs(raw: unknown): SettingsPrefs {
  if (!isRecord(raw)) return DEFAULT_SETTINGS_PREFS;
  const notifications = isRecord(raw.notifications) ? raw.notifications : {};
  return {
    theme: isTheme(raw.theme) ? raw.theme : DEFAULT_SETTINGS_PREFS.theme,
    notifications: {
      kimi: bool(notifications.kimi, DEFAULT_SETTINGS_PREFS.notifications.kimi),
      reminders: bool(notifications.reminders, DEFAULT_SETTINGS_PREFS.notifications.reminders),
      browser: bool(notifications.browser, DEFAULT_SETTINGS_PREFS.notifications.browser),
    },
    recommendForInput: bool(raw.recommendForInput, DEFAULT_SETTINGS_PREFS.recommendForInput),
    aiWatermark: bool(raw.aiWatermark, DEFAULT_SETTINGS_PREFS.aiWatermark),
    learnFromChats: bool(raw.learnFromChats, DEFAULT_SETTINGS_PREFS.learnFromChats),
    voice: isVoice(raw.voice) ? raw.voice : DEFAULT_SETTINGS_PREFS.voice,
    language: isLanguage(raw.language) ? raw.language : DEFAULT_SETTINGS_PREFS.language,
    preferredName: text(raw.preferredName, '').slice(0, 40),
    occupation: text(raw.occupation, '').slice(0, 80),
    instructions: text(raw.instructions, '').slice(0, 1500),
    prompts: readPrompts(raw.prompts),
  };
}

export function readSettingsPrefs(): SettingsPrefs {
  if (typeof localStorage === 'undefined') return DEFAULT_SETTINGS_PREFS;
  try {
    const stored = localStorage.getItem(SETTINGS_PREFS_KEY);
    return stored ? normalizeSettingsPrefs(JSON.parse(stored)) : DEFAULT_SETTINGS_PREFS;
  } catch {
    // Приватный режим / битый JSON — дефолт, настройки не блокируют приложение.
    return DEFAULT_SETTINGS_PREFS;
  }
}

export function writeSettingsPrefs(prefs: SettingsPrefs): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(SETTINGS_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Квота/приватный режим: предпочтение остаётся в памяти до перезагрузки.
  }
}

/** BCP-47 для выбранного языка; `auto` → null (язык остаётся за контекстом СЭД). */
export function languageLocale(preference: LanguagePreference): string | null {
  if (preference === 'auto') return null;
  return preference === 'en' ? 'en-US' : 'ru-RU';
}

const systemPrefersDark = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-color-scheme: dark)').matches;

/** Тема, которую нужно выставить в `data-theme` для выбранного предпочтения. */
export function resolveTheme(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') return systemPrefersDark() ? 'dark' : 'light';
  return preference;
}

/**
 * Применить тему к документу. `system` слушает медиазапрос, пока приложение
 * открыто, и снимает слушатель при смене предпочтения.
 */
export function applyTheme(preference: ThemePreference): () => void {
  if (typeof document === 'undefined') return () => undefined;
  const root = document.documentElement;
  const set = () => {
    root.setAttribute('data-theme', resolveTheme(preference));
  };
  set();
  if (preference !== 'system' || typeof window.matchMedia !== 'function') {
    return () => undefined;
  }
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  query.addEventListener('change', set);
  return () => query.removeEventListener('change', set);
}
