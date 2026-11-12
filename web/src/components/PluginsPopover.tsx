import { useEffect, useId, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { KimiGlyph } from '../icons/kimiNavGlyphs';
import { PLUGINS_CATALOG, RECOMMENDED_PLUGIN_IDS, type PluginItem } from '../mocks/pluginsCatalog';
import { PluginLogo } from './ui/PluginLogo';
import { PopoverSurface } from './ui/PopoverSurface';
import { t } from '../i18n';

export type PluginsPopoverProps = {
  onManage: () => void;
  disabled?: boolean;
};

/**
 * Composer «Плагины» popover — mirror of kimi.ai `.kimi-popover`:
 * 260px translucent panel (r16, hairline inset + 0 4px 16px), a 256px
 * scroll area with sticky Recommended / Installed / More plugins sections
 * and a 36px «Управление плагинами» row under a 0.5px divider.
 */
export function PluginsPopover({ onManage, disabled }: PluginsPopoverProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const recommended = RECOMMENDED_PLUGIN_IDS.map(id =>
    PLUGINS_CATALOG.find(plugin => plugin.id === id)
  ).filter(plugin => plugin !== undefined);
  const installed = PLUGINS_CATALOG.filter(p => p.installed);
  const more = PLUGINS_CATALOG.filter(p => !p.installed && !RECOMMENDED_PLUGIN_IDS.includes(p.id));
  const trayLogos = recommended.slice(0, 3);
  const install = (plugin: PluginItem) => toast(t('plugins.installSoon', { name: plugin.name }));

  const renderRows = (items: PluginItem[], installable: boolean) => (
    <ul className="plugins-pop__list">
      {items.map(plugin => (
        <li key={plugin.id}>
          <button
            type="button"
            className="plugins-pop__row icon-hover"
            role="menuitem"
            onClick={() => (installable ? install(plugin) : undefined)}
          >
            <PluginLogo id={plugin.id} name={plugin.name} accent={plugin.accent} size={18} />
            <span className="plugins-pop__name">{plugin.name}</span>
            {installable ? (
              <span className="plugins-pop__install">{t('plugins.install')}</span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="plugins-pop" ref={rootRef}>
      <button
        type="button"
        className={`composer-bar__btn icon-hover${open ? ' is-open' : ''}`}
        aria-label={t('composer.bar.plugins')}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => setOpen(v => !v)}
      >
        <span className="plugins-pop__stack" aria-hidden>
          {trayLogos.map(plugin => (
            <PluginLogo
              key={plugin.id}
              id={plugin.id}
              name={plugin.name}
              accent={plugin.accent}
              size={20}
            />
          ))}
        </span>
        <span>{t('composer.bar.plugins')}</span>
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        gap={4}
        id={menuId}
        className="plugins-pop__menu"
        role="menu"
        onDismiss={() => setOpen(false)}
      >
        <div className="plugins-pop__scroll">
          <section className="plugins-pop__section" aria-label={t('plugins.recommended')}>
            <div className="plugins-pop__head">
              <h3 className="plugins-pop__heading">{t('plugins.recommended')}</h3>
            </div>
            {renderRows(recommended, true)}
          </section>
          <section className="plugins-pop__section" aria-label={t('plugins.installed')}>
            <div className="plugins-pop__head">
              <h3 className="plugins-pop__heading">{t('plugins.installed')}</h3>
            </div>
            {renderRows(installed, false)}
          </section>
          <section className="plugins-pop__section" aria-label={t('plugins.morePlugins')}>
            <div className="plugins-pop__head">
              <h3 className="plugins-pop__heading">{t('plugins.morePlugins')}</h3>
            </div>
            {renderRows(more, true)}
          </section>
        </div>
        <div className="plugins-pop__divider" />
        <button
          type="button"
          className="plugins-pop__manage icon-hover"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            onManage();
          }}
        >
          <KimiGlyph name="managePlugins" size={14} />
          <span>{t('plugins.manage')}</span>
        </button>
      </PopoverSurface>
    </div>
  );
}
