import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { IconSearch } from '../icons/kimiStroke';
import {
  FEATURED_PLUGIN_IDS,
  PLUGIN_CATEGORIES,
  PLUGINS_CATALOG,
  PLUGIN_SECTION_VISIBLE,
  type PluginCategory,
  type PluginItem,
} from '../mocks/pluginsCatalog';
import { t } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import { PluginLogo } from './ui/PluginLogo';

export type PluginsPageProps = {
  activeTab: 'plugins' | 'skills';
  onTabChange: (tab: 'plugins' | 'skills') => void;
};

type PluginSection = {
  id: PluginCategory;
  labelKey: string;
  items: PluginItem[];
};

/**
 * kimi.ai `/plugins`: one centred 800px column. The sticky head holds the
 * 56/24 page header (20/28 title, 32px search capsule) and the 36px category
 * rail; the rail scroll-jumps between stacked sections, each a 2-up grid of
 * 392×82 cards with a "View …" overflow row.
 */
export function PluginsPage(_props: PluginsPageProps) {
  const [query, setQuery] = useState('');
  const [activeSection, setActiveSection] = useState<PluginCategory>('installed');
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const pageRef = useRef<HTMLDivElement | null>(null);
  const stickyRef = useRef<HTMLDivElement | null>(null);
  const sectionRef = useRef(new Map<string, HTMLElement>());
  const jumpRef = useRef(false);

  const sections: PluginSection[] = useMemo(() => {
    const byId = new Map(PLUGINS_CATALOG.map(plugin => [plugin.id, plugin] as const));
    const featured = FEATURED_PLUGIN_IDS.map(id => byId.get(id)).filter(
      (plugin): plugin is PluginItem => plugin !== undefined
    );
    return PLUGIN_CATEGORIES.map(({ id, labelKey }) => ({
      id,
      labelKey,
      items:
        id === 'installed'
          ? PLUGINS_CATALOG.filter(plugin => plugin.installed)
          : id === 'featured'
            ? featured
            : PLUGINS_CATALOG.filter(plugin => plugin.category === id),
    }));
  }, []);

  const q = query.trim().toLowerCase();
  const visibleSections = useMemo(() => {
    if (!q) return sections;
    return sections
      .map(section => ({
        ...section,
        items: section.items.filter(
          plugin =>
            plugin.name.toLowerCase().includes(q) || plugin.description.toLowerCase().includes(q)
        ),
      }))
      .filter(section => section.items.length > 0);
  }, [q, sections]);

  const jumpTo = useCallback((id: PluginCategory) => {
    const page = pageRef.current;
    const section = sectionRef.current.get(id);
    if (!page || !section) return;
    const stickyHeight = stickyRef.current?.offsetHeight ?? 0;
    const top =
      section.getBoundingClientRect().top - page.getBoundingClientRect().top + page.scrollTop;
    jumpRef.current = true;
    setActiveSection(id);
    page.scrollTo({ top: Math.max(0, top - stickyHeight), behavior: 'smooth' });
  }, []);

  /* Scroll-spy: the rail follows the section crossing the sticky head. */
  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const onScroll = () => {
      if (q) return;
      const stickyHeight = stickyRef.current?.offsetHeight ?? 0;
      const line = page.getBoundingClientRect().top + stickyHeight + 1;
      let current: PluginCategory | null = null;
      for (const [id, element] of sectionRef.current) {
        if (element.getBoundingClientRect().top <= line) current = id as PluginCategory;
      }
      if (current && !jumpRef.current) setActiveSection(current);
      jumpRef.current = false;
    };
    page.addEventListener('scroll', onScroll, { passive: true });
    return () => page.removeEventListener('scroll', onScroll);
  }, [q]);

  const toggleExpanded = (id: PluginCategory) => {
    setExpanded(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAction = (plugin: PluginItem) => {
    toast(
      plugin.installed
        ? t('plugins.useSoon', { name: plugin.name })
        : t('plugins.installSoon', { name: plugin.name })
    );
  };

  return (
    <div className="market-page" data-zone="ZONE_BODY" ref={pageRef}>
      <div className="market-page__inner">
        <div className="market-page__sticky" ref={stickyRef}>
          <header className="market-page__header">
            <div className="market-page__heading">
              <h1>{t('plugins.title')}</h1>
              <p>{t('plugins.subtitle')}</p>
            </div>
            <label className="market-page__search">
              <IconSearch size={18} />
              <input
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={t('plugins.search')}
                aria-label={t('plugins.search')}
              />
            </label>
          </header>

          <nav className="market-page__cats" aria-label={t('plugins.tabs')}>
            <div className="market-cats__scroll" role="tablist">
              {PLUGIN_CATEGORIES.map(cat => (
                <button
                  key={cat.id}
                  type="button"
                  role="tab"
                  aria-selected={activeSection === cat.id}
                  className={`market-cat${activeSection === cat.id ? ' is-active' : ''}`}
                  onClick={() => jumpTo(cat.id)}
                >
                  {t(cat.labelKey as MessageKey)}
                </button>
              ))}
            </div>
          </nav>
        </div>

        {visibleSections.map(section => {
          const expandedNow = expanded.has(section.id) || Boolean(q);
          const cards = expandedNow
            ? section.items
            : section.items.slice(0, PLUGIN_SECTION_VISIBLE);
          const tail = section.items.slice(PLUGIN_SECTION_VISIBLE);
          return (
            <section
              key={section.id}
              className={`market-plugin-section${section.id === 'installed' ? ' is-first' : ''}`}
              aria-label={t(section.labelKey as MessageKey)}
              ref={element => {
                if (element) sectionRef.current.set(section.id, element);
                else sectionRef.current.delete(section.id);
              }}
            >
              {section.id !== 'installed' ? (
                <h2 className="market-plugin-section__title">
                  {t(section.labelKey as MessageKey)}
                </h2>
              ) : null}
              <div className="market-list">
                {cards.map(plugin => (
                  <article key={plugin.id} className="market-card">
                    <span className="market-card__icon" aria-hidden>
                      <PluginLogo
                        id={plugin.id}
                        name={plugin.name}
                        accent={plugin.accent}
                        size={46}
                      />
                    </span>
                    <div className="market-card__body">
                      <h3 className="market-card__title">{plugin.name}</h3>
                      <p className="market-card__desc">{plugin.description}</p>
                    </div>
                    <div className="market-card__actions">
                      <button
                        type="button"
                        className="market-card__cta"
                        onClick={() => handleAction(plugin)}
                      >
                        {plugin.installed ? t('plugins.use') : t('plugins.install')}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
              {!expandedNow && tail.length > 0 ? (
                <button
                  type="button"
                  className="market-plugin-overflow"
                  onClick={() => toggleExpanded(section.id)}
                >
                  <span className="market-plugin-overflow__icons" aria-hidden>
                    {tail.slice(0, 3).map(plugin => (
                      <span key={plugin.id} className="market-plugin-overflow__icon">
                        <PluginLogo
                          id={plugin.id}
                          name={plugin.name}
                          accent={plugin.accent}
                          size={24}
                        />
                      </span>
                    ))}
                  </span>
                  <span className="market-plugin-overflow__label">
                    {t('plugins.viewMore')}{' '}
                    {tail
                      .slice(0, 2)
                      .map(plugin => plugin.name)
                      .join(', ')}
                    {tail.length > 2 ? ` ${t('plugins.andMore', { count: tail.length - 2 })}` : ''}
                  </span>
                </button>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
