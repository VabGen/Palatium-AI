import { useEffect, useId, useMemo, useState } from 'react';
import { IconChevronDown, IconPlus, IconSearch, IconTrash } from '../icons/kimiStroke';
import {
  SettingsGlyph,
  SettingsChromeGlyph,
  type SettingsGlyphName,
  type SettingsChromeName,
} from '../icons/kimiSettingsGlyphs';
import { getI18nLocale, resolveLanguage, t } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import { setLangOverride } from '../runtime/store';
import { KimiMenu } from './ui/KimiDropdown';
import { KimiDialog } from './KimiDialog';
import {
  applyTheme,
  languageLocale,
  readSettingsPrefs,
  writeSettingsPrefs,
  type LanguagePreference,
  type SavedPrompt,
  type SettingsPrefs,
  type ThemePreference,
  type VoiceId,
} from '../lib/settingsPrefs';
import themePreviewLight from '../assets/theme/theme-preview-light.png';
import themePreviewSystem from '../assets/theme/theme-preview-system.png';
import themePreviewDark from '../assets/theme/theme-preview-dark.png';
import type { SettingsSectionId } from '../lib/shellView';

type SettingsNavItem = {
  readonly id: SettingsSectionId;
  readonly label: MessageKey;
  readonly glyph: SettingsGlyphName;
  /** kimi.ai renders nav as three groups; groups 1–2 carry a 36px heading row. */
  readonly group: 0 | 1 | 2;
};

const SETTINGS_NAV_GROUPS: readonly { id: 0 | 1 | 2; title: MessageKey | null }[] = [
  { id: 0, title: null },
  { id: 2, title: 'settings.nav.group.personalization' },
];

/** Subscription / billing / gift-cards omitted — Palatium has no plan commerce. */
export const SETTINGS_SECTIONS: readonly SettingsNavItem[] = [
  { id: 'account', label: 'settings.nav.account', glyph: 'account', group: 0 },
  {
    id: 'notifications',
    label: 'settings.nav.notifications',
    glyph: 'notifications',
    group: 0,
  },
  { id: 'appearance', label: 'settings.nav.appearance', glyph: 'appearance', group: 0 },
  { id: 'speech', label: 'settings.nav.speech', glyph: 'speech', group: 0 },
  { id: 'shortcuts', label: 'settings.nav.shortcuts', glyph: 'shortcuts', group: 0 },
  { id: 'features', label: 'settings.nav.features', glyph: 'features', group: 0 },
  { id: 'memory', label: 'settings.nav.memory', glyph: 'memory', group: 2 },
  { id: 'chat', label: 'settings.nav.chat', glyph: 'chat', group: 2 },
  { id: 'prompts', label: 'settings.nav.prompts', glyph: 'prompts', group: 2 },
];

const OCCUPATIONS = [
  'Product',
  'Engineering',
  'Design',
  'Marketing',
  'Sales',
  'Finance',
  'Operations',
  'Legal',
  'Education',
  'Other',
] as const;

type SettingsPageProps = {
  section: SettingsSectionId;
  onSection: (section: SettingsSectionId) => void;
  onBack: () => void;
  userName: string | null;
};

/**
 * kimi.ai `/settings/*` — full-page settings layer.
 *
 * Left nav replaces the history sidebar (240px, ground canvas), the content is a
 * white panel inset from the shell with an 800px reading column. Geometry is
 * measured from the live product: 224×36 nav rows (r12), 768px cards (r16, 3%
 * fill), 48px rows, 44×24 switches.
 */
export function SettingsPage({ section, onSection, onBack, userName }: SettingsPageProps) {
  const [prefs, setPrefs] = useState<SettingsPrefs>(readSettingsPrefs);
  const [notice, setNotice] = useState<'logout' | 'delete' | null>(null);

  useEffect(() => {
    const cleanup = applyTheme(prefs.theme);
    return cleanup;
  }, [prefs.theme]);

  const update = (patch: Partial<SettingsPrefs>) => {
    setPrefs(prev => {
      const next = { ...prev, ...patch };
      writeSettingsPrefs(next);
      return next;
    });
  };

  const displayName = userName?.trim() || t('sidebar.profile');
  const initials = useMemo(() => {
    const parts = displayName.split(/\s+/).filter(Boolean);
    const letters = parts.slice(0, 2).map(part => part[0]?.toUpperCase() ?? '');
    return letters.join('') || 'P';
  }, [displayName]);

  return (
    <div className="settings-layer">
      <aside className="settings-nav">
        <button type="button" className="settings-nav__back icon-hover" onClick={onBack}>
          <SettingsChromeGlyph name="chevronLeft" size={18} />
          <span>{t('settings.back')}</span>
        </button>
        <nav className="settings-nav__list" aria-label={t('sidebar.nav')}>
          {SETTINGS_NAV_GROUPS.map(group => (
            <section className="settings-nav__group" key={group.id}>
              {group.title ? <h3 className="settings-nav__group-title">{t(group.title)}</h3> : null}
              <div className="settings-nav__group-card">
                {SETTINGS_SECTIONS.filter(item => item.group === group.id).map(item => (
                  <button
                    key={item.id}
                    type="button"
                    className={`settings-nav__item${item.id === section ? ' is-active' : ''}`}
                    aria-current={item.id === section ? 'page' : undefined}
                    onClick={() => onSection(item.id)}
                  >
                    <SettingsGlyph name={item.glyph} size={18} />
                    <span>{t(item.label)}</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>
      </aside>

      <div className="settings-panel">
        <div className="settings-panel__header" aria-hidden />
        <div className="settings-panel__body">
          <div className={`settings-page${section === 'account' ? ' settings-page--fill' : ''}`}>
            {section === 'account' ? (
              <AccountSection
                displayName={displayName}
                initials={initials}
                onLogOut={() => setNotice('logout')}
                onDelete={() => setNotice('delete')}
              />
            ) : null}
            {section === 'notifications' ? (
              <NotificationsSection prefs={prefs} update={update} />
            ) : null}
            {section === 'appearance' ? <AppearanceSection prefs={prefs} update={update} /> : null}
            {section === 'speech' ? <SpeechSection prefs={prefs} update={update} /> : null}
            {section === 'shortcuts' ? <ShortcutsSection /> : null}
            {section === 'features' ? <FeaturesSection prefs={prefs} update={update} /> : null}
            {section === 'memory' ? <MemorySection prefs={prefs} update={update} /> : null}
            {section === 'chat' ? <ChatSettingsSection prefs={prefs} update={update} /> : null}
            {section === 'prompts' ? <PromptsSection prefs={prefs} update={update} /> : null}
          </div>
        </div>
      </div>

      <KimiDialog
        open={notice !== null}
        title={notice === 'delete' ? t('settings.account.delete') : t('settings.account.logOut')}
        description={
          notice === 'delete' ? t('settings.account.deleteBody') : t('settings.account.logoutBody')
        }
        closeLabel={t('settings.dialog.close')}
        onClose={() => setNotice(null)}
      >
        <div />
      </KimiDialog>
    </div>
  );
}

function AccountSection({
  displayName,
  initials,
  onLogOut,
  onDelete,
}: {
  displayName: string;
  initials: string;
  onLogOut: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <div className="settings-profile">
        <label className="settings-profile__avatar">
          <span className="settings-profile__avatar-initials" aria-hidden>
            {initials}
          </span>
          <span className="settings-profile__avatar-mask" aria-hidden>
            <SettingsChromeGlyph name="camera" size={24} />
          </span>
        </label>
        <div className="settings-profile__name">
          <span className="settings-profile__name-text">{displayName}</span>
          <button
            type="button"
            className="settings-profile__edit"
            aria-label={t('settings.account.editName')}
          >
            <SettingsChromeGlyph name="edit" size={20} />
          </button>
        </div>
      </div>

      <section className="settings-section">
        <h3 className="settings-section__title">{t('settings.account.linked')}</h3>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-row__leading">
              <span className="settings-row__icon" aria-hidden>
                <SettingsChromeGlyph name="mobile" size={18} />
              </span>
              <span className="settings-row__label">{t('settings.account.phone')}</span>
            </div>
            <div className="settings-row__control">
              <span className="settings-row__value">{t('settings.account.notLinked')}</span>
              <button type="button" className="settings-link">
                {t('settings.account.add')}
              </button>
            </div>
          </div>
          <div className="settings-row">
            <div className="settings-row__leading">
              <span className="settings-row__label">{t('settings.account.email')}</span>
            </div>
            <div className="settings-row__control">
              <span className="settings-row__value">{t('settings.account.notLinked')}</span>
              <button type="button" className="settings-link">
                {t('settings.account.link')}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h3 className="settings-section__title">{t('settings.account.security')}</h3>
        <div className="settings-card">
          <button type="button" className="settings-row settings-row--clickable">
            <div className="settings-row__leading">
              <span className="settings-row__label">{t('settings.account.devices')}</span>
            </div>
            <div className="settings-row__control">
              <span className="settings-row__value">{t('settings.account.thisDevice')}</span>
              <SettingsChromeGlyph name="chevronRight" size={18} />
            </div>
          </button>
        </div>
      </section>

      <div className="settings-actions">
        <button
          type="button"
          className="settings-button settings-button--secondary settings-button--block settings-button--with-icon"
          onClick={onLogOut}
        >
          <SettingsChromeGlyph name="signOut" size={20} />
          {t('settings.account.logOut')}
        </button>
      </div>

      <button type="button" className="settings-deregister" onClick={onDelete}>
        {t('settings.account.delete')}
      </button>
    </>
  );
}

function Switch({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (next: boolean) => void;
}) {
  const id = useId();
  return (
    <label className={`settings-switch${checked ? ' is-on' : ''}`} htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        className="settings-switch__input"
        checked={checked}
        aria-label={label}
        onChange={event => onChange(event.target.checked)}
      />
      <span className="settings-switch__track" aria-hidden>
        <span className="settings-switch__thumb" />
      </span>
    </label>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="settings-row settings-row--toggle">
      <div className="settings-row__leading">
        <span className="settings-row__label">{label}</span>
        <p className="settings-row__desc">{description}</p>
      </div>
      <div className="settings-row__control">
        <Switch checked={checked} label={label} onChange={onChange} />
      </div>
    </div>
  );
}

function NotificationsSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  const set = (key: keyof SettingsPrefs['notifications']) => (next: boolean) =>
    update({ notifications: { ...prefs.notifications, [key]: next } });
  return (
    <>
      <div className="settings-card">
        <ToggleRow
          label={t('settings.notifications.kimi')}
          description={t('settings.notifications.kimiDesc')}
          checked={prefs.notifications.kimi}
          onChange={set('kimi')}
        />
        <ToggleRow
          label={t('settings.notifications.reminders')}
          description={t('settings.notifications.remindersDesc')}
          checked={prefs.notifications.reminders}
          onChange={set('reminders')}
        />
        <ToggleRow
          label={t('settings.notifications.browser')}
          description={t('settings.notifications.browserDesc')}
          checked={prefs.notifications.browser}
          onChange={set('browser')}
        />
      </div>
      <div className="settings-notification-preview" aria-hidden>
        <div className="settings-notification-preview__card">
          <span className="settings-notification-preview__logo">P</span>
          <span className="settings-notification-preview__copy">
            <span className="settings-notification-preview__title">{t('app.title')}</span>
            <span className="settings-notification-preview__body">
              {t('settings.notifications.kimiDesc')}
            </span>
          </span>
        </div>
      </div>
    </>
  );
}

const THEME_OPTIONS: readonly {
  id: ThemePreference;
  label: MessageKey;
  glyph: SettingsChromeName;
  preview: string;
}[] = [
  {
    id: 'light',
    label: 'settings.appearance.light',
    glyph: 'lightMode',
    preview: themePreviewLight,
  },
  {
    id: 'system',
    label: 'settings.appearance.system',
    glyph: 'followSystem',
    preview: themePreviewSystem,
  },
  {
    id: 'dark',
    label: 'settings.appearance.dark',
    glyph: 'darkMode',
    preview: themePreviewDark,
  },
];

/**
 * Языки интерфейса. Витрина kimi.ai перечисляет все локали бренда; у нас
 * перевод есть только для двух, поэтому список = реальная возможность, а не
 * копия чужого перечня (мёртвые пункты — ложный UX).
 */
const LANGUAGE_OPTIONS: readonly { id: Exclude<LanguagePreference, 'auto'>; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'ru', label: 'Русский' },
];

function AppearanceSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  const activeLanguage =
    prefs.language === 'auto' ? resolveLanguage(getI18nLocale()) : prefs.language;

  const selectLanguage = (id: Exclude<LanguagePreference, 'auto'>) => {
    update({ language: id });
    setLangOverride(languageLocale(id));
  };

  return (
    <>
      <section className="settings-section">
        <h3 className="settings-section__title">{t('settings.appearance.theme')}</h3>
        <div className="settings-theme-grid">
          {THEME_OPTIONS.map(option => (
            <button
              key={option.id}
              type="button"
              className={`settings-theme-card${prefs.theme === option.id ? ' is-active' : ''}`}
              aria-pressed={prefs.theme === option.id}
              onClick={() => update({ theme: option.id })}
            >
              <span className="settings-theme-card__preview">
                <img
                  className="settings-theme-card__preview-img"
                  src={option.preview}
                  alt=""
                  draggable={false}
                />
              </span>
              <span className="settings-theme-card__label">
                <SettingsChromeGlyph name={option.glyph} size={18} />
                {t(option.label)}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="settings-section">
        <h3 className="settings-section__title">{t('settings.appearance.language')}</h3>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-row__leading">
              <div className="settings-row__main">
                <div className="settings-row__label">{t('settings.appearance.language')}</div>
              </div>
            </div>
            <div className="settings-row__control">
              <KimiMenu
                label={t('settings.appearance.language')}
                triggerClassName="settings-language__trigger"
                menuClassName="settings-language__menu"
                trigger={
                  <>
                    <span className="settings-language__value">
                      {LANGUAGE_OPTIONS.find(option => option.id === activeLanguage)?.label}
                    </span>
                    <SettingsChromeGlyph name="upDown" size={18} />
                  </>
                }
              >
                {LANGUAGE_OPTIONS.map(option => {
                  const isActive = option.id === activeLanguage;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={isActive}
                      className={`settings-language__item${isActive ? ' is-active' : ''}`}
                      onClick={() => selectLanguage(option.id)}
                    >
                      <span>{option.label}</span>
                      {isActive ? <SettingsChromeGlyph name="check" size={16} /> : null}
                    </button>
                  );
                })}
              </KimiMenu>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function SpeechSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  const voices: readonly { id: VoiceId; label: MessageKey }[] = [
    { id: 'kimi', label: 'settings.speech.kimi' },
    { id: 'warm', label: 'settings.speech.warm' },
  ];
  return (
    <section className="settings-section">
      <h3 className="settings-section__title">{t('settings.speech.chooseVoice')}</h3>
      <div className="settings-card">
        {voices.map(voice => (
          <button
            key={voice.id}
            type="button"
            className={`settings-voice${prefs.voice === voice.id ? ' is-active' : ''}`}
            aria-pressed={prefs.voice === voice.id}
            onClick={() => update({ voice: voice.id })}
          >
            <span className="settings-voice__wave" aria-hidden>
              <span />
              <span />
              <span />
              <span />
              <span />
            </span>
            <span className="settings-voice__label">{t(voice.label)}</span>
            {prefs.voice === voice.id ? <span className="settings-voice__check">✓</span> : null}
          </button>
        ))}
      </div>
    </section>
  );
}

function ShortcutsSection() {
  const rows: readonly { label: MessageKey; keys: string }[] = [
    { label: 'settings.shortcuts.newChat', keys: 'Ctrl K' },
    { label: 'settings.shortcuts.toggleSidebar', keys: 'Ctrl B' },
    { label: 'settings.shortcuts.voice', keys: 'Hold Ctrl J' },
  ];
  return (
    <div className="settings-card">
      {rows.map(row => (
        <div key={row.label} className="settings-row">
          <div className="settings-row__leading">
            <span className="settings-row__label">{t(row.label)}</span>
          </div>
          <div className="settings-row__control">
            <kbd className="settings-kbd">{row.keys}</kbd>
          </div>
        </div>
      ))}
    </div>
  );
}

function FeaturesSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  return (
    <div className="settings-card">
      <ToggleRow
        label={t('settings.features.recommend')}
        description={t('settings.features.recommendDesc')}
        checked={prefs.recommendForInput}
        onChange={next => update({ recommendForInput: next })}
      />
      <ToggleRow
        label={t('settings.features.watermark')}
        description={t('settings.features.watermarkDesc')}
        checked={prefs.aiWatermark}
        onChange={next => update({ aiWatermark: next })}
      />
    </div>
  );
}

function MemorySection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  return (
    <>
      <div className="settings-card">
        <ToggleRow
          label={t('settings.memory.learn')}
          description={t('settings.memory.learnDesc')}
          checked={prefs.learnFromChats}
          onChange={next => update({ learnFromChats: next })}
        />
      </div>
      <div className="settings-card settings-card--spaced">
        <div className="settings-row settings-row--stack">
          <div className="settings-row__leading">
            <span className="settings-row__label">{t('settings.memory.space')}</span>
            <p className="settings-row__desc">{t('settings.memory.spaceDesc')}</p>
          </div>
          <div className="settings-row__control">
            <button type="button" className="settings-button settings-button--secondary">
              {t('settings.memory.import')}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function ChatSettingsSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  const [name, setName] = useState(prefs.preferredName);
  const [occupation, setOccupation] = useState(prefs.occupation);
  const [instructions, setInstructions] = useState(prefs.instructions);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 2000);
    return () => window.clearTimeout(timer);
  }, [saved]);

  return (
    <div className="settings-form">
      <div className="settings-form__row">
        <label className="settings-field">
          <span className="settings-field__label">{t('settings.chat.name')}</span>
          <input
            className="settings-field__control"
            value={name}
            maxLength={40}
            onChange={event => setName(event.target.value)}
          />
        </label>
        <label className="settings-field">
          <span className="settings-field__label">{t('settings.chat.occupation')}</span>
          <span className="settings-field__control settings-field__control--select">
            <select
              value={occupation}
              aria-label={t('settings.chat.occupation')}
              onChange={event => setOccupation(event.target.value)}
            >
              <option value="">{t('settings.chat.occupationHint')}</option>
              {OCCUPATIONS.map(item => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <IconChevronDown size={16} aria-hidden />
          </span>
        </label>
      </div>
      <label className="settings-field settings-field--wide">
        <span className="settings-field__label">{t('settings.chat.instructions')}</span>
        <span className="settings-field__control settings-field__control--area">
          <textarea
            className="settings-field__textarea"
            value={instructions}
            maxLength={1500}
            onChange={event => setInstructions(event.target.value)}
          />
          <span className="settings-field__counter">
            {t('settings.chat.counter', { used: instructions.length, limit: 1500 })}
          </span>
        </span>
      </label>
      <div className="settings-form__actions">
        {saved ? <span className="settings-form__saved">{t('settings.chat.saved')}</span> : null}
        <button
          type="button"
          className="settings-button settings-button--primary"
          onClick={() => {
            update({ preferredName: name.trim(), occupation, instructions });
            setSaved(true);
          }}
        >
          {t('settings.chat.save')}
        </button>
      </div>
    </div>
  );
}

function PromptsSection({
  prefs,
  update,
}: {
  prefs: SettingsPrefs;
  update: (patch: Partial<SettingsPrefs>) => void;
}) {
  const [query, setQuery] = useState('');
  const [draftOpen, setDraftOpen] = useState(false);
  const [trigger, setTrigger] = useState('');
  const [content, setContent] = useState('');

  const rows = prefs.prompts.filter(prompt => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return (
      prompt.trigger.toLowerCase().includes(needle) || prompt.content.toLowerCase().includes(needle)
    );
  });

  const addPrompt = () => {
    const cleanTrigger = trigger.trim();
    const cleanContent = content.trim();
    if (!cleanTrigger || !cleanContent) return;
    const prompt: SavedPrompt = {
      id: `p-${Date.now().toString(36)}`,
      trigger: cleanTrigger,
      content: cleanContent,
    };
    update({ prompts: [...prefs.prompts, prompt] });
    setTrigger('');
    setContent('');
    setDraftOpen(false);
  };

  return (
    <>
      <div className="settings-toolbar">
        <label className="settings-search">
          <IconSearch size={16} aria-hidden />
          <input
            value={query}
            placeholder={t('settings.prompts.search')}
            aria-label={t('settings.prompts.search')}
            onChange={event => setQuery(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="settings-button settings-button--primary"
          onClick={() => setDraftOpen(true)}
        >
          <IconPlus size={16} aria-hidden />
          {t('settings.prompts.add')}
        </button>
      </div>

      <div className="settings-table settings-table--prompts">
        <div className="settings-table__head" role="row">
          <span>{t('settings.prompts.trigger')}</span>
          <span>{t('settings.prompts.content')}</span>
          <span />
        </div>
        {rows.length === 0 ? (
          <div className="settings-table__empty">{t('settings.prompts.empty')}</div>
        ) : (
          rows.map(prompt => (
            <div key={prompt.id} className="settings-table__row">
              <span className="settings-table__cell">{prompt.trigger}</span>
              <span className="settings-table__cell is-clipped">{prompt.content}</span>
              <span className="settings-table__cell is-end">
                <button
                  type="button"
                  className="settings-icon-button icon-hover"
                  aria-label={t('settings.prompts.delete')}
                  title={t('settings.prompts.delete')}
                  onClick={() =>
                    update({ prompts: prefs.prompts.filter(row => row.id !== prompt.id) })
                  }
                >
                  <IconTrash size={16} />
                </button>
              </span>
            </div>
          ))
        )}
      </div>

      <KimiDialog
        open={draftOpen}
        title={t('settings.prompts.add')}
        closeLabel={t('settings.cancel')}
        onClose={() => setDraftOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="settings-button settings-button--secondary"
              onClick={() => setDraftOpen(false)}
            >
              {t('settings.cancel')}
            </button>
            <button
              type="button"
              className="settings-button settings-button--primary"
              disabled={!trigger.trim() || !content.trim()}
              onClick={addPrompt}
            >
              {t('settings.chat.save')}
            </button>
          </>
        }
      >
        <label className="settings-field settings-field--wide">
          <span className="settings-field__label">{t('settings.prompts.trigger')}</span>
          <input
            className="settings-field__control"
            value={trigger}
            placeholder={t('settings.prompts.hint')}
            onChange={event => setTrigger(event.target.value)}
          />
        </label>
        <label className="settings-field settings-field--wide">
          <span className="settings-field__label">{t('settings.prompts.content')}</span>
          <span className="settings-field__control settings-field__control--area">
            <textarea
              className="settings-field__textarea"
              value={content}
              onChange={event => setContent(event.target.value)}
            />
          </span>
        </label>
      </KimiDialog>
    </>
  );
}
