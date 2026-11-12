import { useId, useRef, useState, type RefObject } from 'react';
import { IconCheck, IconChevronLeft, IconGlobe } from '../icons/kimiStroke';
import { KimiToolkitGlyph, type KimiToolkitName } from '../icons/kimiToolkitGlyphs';
import { PLUGINS_CATALOG, TOOLKIT_PLUGIN_IDS } from '../mocks/pluginsCatalog';
import { PluginLogo } from './ui/PluginLogo';
import { PopoverSurface } from './ui/PopoverSurface';

export type SlashAction =
  | { kind: 'attach' }
  | { kind: 'plugins' }
  | { kind: 'skills' }
  | { kind: 'goal' }
  | { kind: 'plugin'; id: string }
  | { kind: 'webSearch'; mode: 'auto' | 'off' };

export type SlashPaletteProps = {
  open: boolean;
  /** Composer card the list is anchored to and spans. */
  anchorRef: RefObject<HTMLElement | null>;
  /** The `+` trigger: its own click toggles, so it must not dismiss first. */
  triggerRef?: RefObject<HTMLElement | null>;
  /** Whole capsule — kept open while the pointer is over it. */
  keepOpenRef?: RefObject<HTMLElement | null>;
  onDismiss: () => void;
  /**
   * kimi.ai home toolkit vs in-thread `+` menu.
   * Chat: add files + web search (no Cluster / plugins / skills).
   */
  variant?: 'home' | 'chat';
  /** Current web-search preference for the nested panel checkmark. */
  webSearchMode?: 'auto' | 'off';
  labels: {
    addFiles: string;
    plugins: string;
    pluginsDesc: string;
    skills: string;
    skillsDesc: string;
    goal: string;
    goalDesc: string;
    webSearch: string;
    webSearchDesc: string;
    webSearchBack: string;
    webSearchAuto: string;
    webSearchAutoDesc: string;
    webSearchOff: string;
    webSearchOffDesc: string;
  };
  onSelect: (action: SlashAction) => void;
};

type HomeRow = {
  action: SlashAction;
  glyph: KimiToolkitName;
  labelKey: keyof SlashPaletteProps['labels'];
  descKey?: keyof SlashPaletteProps['labels'];
};

const HOME_CORE: HomeRow[] = [
  { action: { kind: 'attach' }, glyph: 'addFiles', labelKey: 'addFiles' },
  {
    action: { kind: 'plugins' },
    glyph: 'plugins',
    labelKey: 'plugins',
    descKey: 'pluginsDesc',
  },
  {
    action: { kind: 'skills' },
    glyph: 'skills',
    labelKey: 'skills',
    descKey: 'skillsDesc',
  },
  {
    action: { kind: 'goal' },
    glyph: 'goal',
    labelKey: 'goal',
    descKey: 'goalDesc',
  },
];

const TOOLKIT_PLUGINS = TOOLKIT_PLUGIN_IDS.map(id =>
  PLUGINS_CATALOG.find(plugin => plugin.id === id)
).filter(plugin => plugin !== undefined);

type Panel = 'root' | 'webSearch';

/**
 * Toolkit menu attached to the composer's `+` (kimi.ai `.toolkit-panel`).
 *
 * Kimi hangs a 768px translucent panel (r24, blur 6, white 90%) off the *editor
 * card's* bottom edge — not the capsule's, whose grey tray band sits 48px lower.
 * Rows are a single 36px line: 18px icon, label, then the grey description
 * inline (`.toolkit-item__description`), never a stacked two-line cell.
 *
 * In an active chat the menu is only «Add files» + «Web search» (Cluster omitted).
 */
export function SlashPalette({
  open,
  anchorRef,
  triggerRef,
  keepOpenRef,
  onDismiss,
  variant = 'home',
  webSearchMode = 'auto',
  labels,
  onSelect,
}: SlashPaletteProps) {
  const listId = useId();
  const fallbackRef = useRef<HTMLElement | null>(null);
  const [panel, setPanel] = useState<Panel>('root');
  // Closed palette always paints root; remount via `key` from Composer resets nest.
  const activePanel: Panel = open ? panel : 'root';

  const isChat = variant === 'chat';

  return (
    <PopoverSurface
      open={open}
      rootRef={fallbackRef}
      anchorRef={anchorRef}
      // Chat composer sits on the bottom edge — hang the toolkit above it.
      // Home editor has room below; side=bottom matches kimi `.toolkit-panel`.
      side={isChat ? 'top' : 'bottom'}
      gap={10}
      matchWidth
      id={listId}
      className={`slash-palette${isChat ? ' slash-palette--chat' : ''}${
        activePanel === 'webSearch' ? ' slash-palette--nested' : ''
      }`}
      role="listbox"
      label={labels.plugins}
      onDismiss={onDismiss}
      keepOpenRefs={[
        anchorRef,
        ...(triggerRef ? [triggerRef] : []),
        ...(keepOpenRef ? [keepOpenRef] : []),
      ]}
    >
      {activePanel === 'webSearch' ? (
        <ul className="slash-palette__list">
          <li>
            <button
              type="button"
              className="slash-palette__item slash-palette__item--back icon-hover"
              onClick={() => setPanel('root')}
            >
              <IconChevronLeft size={16} aria-hidden />
              <span className="slash-palette__label">{labels.webSearchBack}</span>
            </button>
          </li>
          <li>
            <button
              type="button"
              className={`slash-palette__item slash-palette__item--choice icon-hover${
                webSearchMode === 'auto' ? ' is-selected' : ''
              }`}
              role="option"
              aria-selected={webSearchMode === 'auto'}
              onClick={() => onSelect({ kind: 'webSearch', mode: 'auto' })}
            >
              <span className="slash-palette__choice-text">
                <span className="slash-palette__label">{labels.webSearchAuto}</span>
                <span className="slash-palette__desc">{labels.webSearchAutoDesc}</span>
              </span>
              {webSearchMode === 'auto' ? (
                <IconCheck size={16} className="slash-palette__check" aria-hidden />
              ) : null}
            </button>
          </li>
          <li>
            <button
              type="button"
              className={`slash-palette__item slash-palette__item--choice icon-hover${
                webSearchMode === 'off' ? ' is-selected' : ''
              }`}
              role="option"
              aria-selected={webSearchMode === 'off'}
              onClick={() => onSelect({ kind: 'webSearch', mode: 'off' })}
            >
              <span className="slash-palette__choice-text">
                <span className="slash-palette__label">{labels.webSearchOff}</span>
                <span className="slash-palette__desc">{labels.webSearchOffDesc}</span>
              </span>
              {webSearchMode === 'off' ? (
                <IconCheck size={16} className="slash-palette__check" aria-hidden />
              ) : null}
            </button>
          </li>
        </ul>
      ) : isChat ? (
        <ul className="slash-palette__list">
          <li>
            <button
              type="button"
              className="slash-palette__item slash-palette__item--primary icon-hover"
              role="option"
              onClick={() => onSelect({ kind: 'attach' })}
            >
              <KimiToolkitGlyph name="addFiles" size={18} />
              <span className="slash-palette__label">{labels.addFiles}</span>
            </button>
          </li>
          <li>
            <button
              type="button"
              className="slash-palette__item icon-hover"
              role="option"
              onClick={() => setPanel('webSearch')}
            >
              <IconGlobe size={18} />
              <span className="slash-palette__label">{labels.webSearch}</span>
              <span className="slash-palette__desc">{labels.webSearchDesc}</span>
            </button>
          </li>
        </ul>
      ) : (
        <ul className="slash-palette__list">
          {HOME_CORE.map(row => (
            <li key={row.labelKey}>
              <button
                type="button"
                className="slash-palette__item icon-hover"
                role="option"
                onClick={() => onSelect(row.action)}
              >
                <KimiToolkitGlyph name={row.glyph} size={18} />
                <span className="slash-palette__label">{labels[row.labelKey]}</span>
                {row.descKey ? (
                  <span className="slash-palette__desc">{labels[row.descKey]}</span>
                ) : null}
              </button>
            </li>
          ))}
          {TOOLKIT_PLUGINS.map(plugin => (
            <li key={plugin.id}>
              <button
                type="button"
                className="slash-palette__item icon-hover"
                role="option"
                onClick={() => onSelect({ kind: 'plugin', id: plugin.id })}
              >
                <PluginLogo id={plugin.id} name={plugin.name} accent={plugin.accent} size={18} />
                <span className="slash-palette__label">{plugin.name}</span>
                <span className="slash-palette__desc">{plugin.description}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </PopoverSurface>
  );
}
