import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { IconChevronDown, IconFileText, IconSearch, IconSpark } from '../icons/kimiStroke';
import {
  FEATURED_SKILL_IDS,
  SKILL_CATEGORIES,
  SKILL_SECTION_VISIBLE,
  SKILLS_CATALOG,
  type SkillCategory,
  type SkillItem,
} from '../mocks/skillsCatalog';
import { t } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import { PopoverSurface } from './ui/PopoverSurface';

export type SkillsPageProps = {
  activeTab: 'plugins' | 'skills';
  onTabChange: (tab: 'plugins' | 'skills') => void;
};

type SkillSection = {
  id: SkillCategory;
  labelKey: string;
  items: SkillItem[];
};

/**
 * kimi.ai `/skills`: one centred 800px column. Sticky head = 56/16 page header
 * (20/28 title, 14/20 subtitle, 32px search switch, 108×32 dark «Customize»)
 * + 36px pill rail; below, stacked sections of 392×132 cards (44px tile, title
 * row + 52×26 Add, 12/18 meta, 2-line description) and a text-only "View …"
 * overflow row. The rail scroll-spies and scroll-jumps, exactly like `/plugins`.
 */
export function SkillsPage(_props: SkillsPageProps) {
  const [query, setQuery] = useState('');
  const [activeSection, setActiveSection] = useState<SkillCategory>('added');
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const [addedIds, setAddedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const pageRef = useRef<HTMLDivElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const catsRef = useRef<HTMLElement | null>(null);
  const customizeRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const sectionRef = useRef(new Map<string, HTMLElement>());
  const jumpRef = useRef(false);
  const menuId = useId();

  const sections: SkillSection[] = useMemo(() => {
    const byId = new Map(SKILLS_CATALOG.map(skill => [skill.id, skill] as const));
    const featured = FEATURED_SKILL_IDS.map(id => byId.get(id)).filter(
      (skill): skill is SkillItem => skill !== undefined
    );
    return SKILL_CATEGORIES.map(({ id, labelKey }) => ({
      id,
      labelKey,
      items:
        id === 'added'
          ? SKILLS_CATALOG.filter(skill => addedIds.has(skill.id))
          : id === 'featured'
            ? featured
            : SKILLS_CATALOG.filter(skill => skill.category === id),
    }));
  }, [addedIds]);

  const q = query.trim().toLowerCase();
  const visibleSections = useMemo(() => {
    if (!q) return sections;
    return sections
      .map(section => ({
        ...section,
        items: section.items.filter(
          skill =>
            skill.name.toLowerCase().includes(q) || skill.description.toLowerCase().includes(q)
        ),
      }))
      .filter(section => section.items.length > 0);
  }, [q, sections]);

  const jumpTo = useCallback((id: SkillCategory) => {
    const page = pageRef.current;
    const section = sectionRef.current.get(id);
    if (!page || !section) return;
    const barHeight = (headerRef.current?.offsetHeight ?? 0) + (catsRef.current?.offsetHeight ?? 0);
    const top =
      section.getBoundingClientRect().top - page.getBoundingClientRect().top + page.scrollTop;
    jumpRef.current = true;
    setActiveSection(id);
    /* kimi.ai lands the section title 8px below the sticky category rail. */
    page.scrollTo({ top: Math.max(0, top - barHeight - 8), behavior: 'smooth' });
  }, []);

  /* Scroll-spy: the rail follows the section crossing the sticky head. */
  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const onScroll = () => {
      if (q) return;
      const barHeight =
        (headerRef.current?.offsetHeight ?? 0) + (catsRef.current?.offsetHeight ?? 0);
      const line = page.getBoundingClientRect().top + barHeight + 9;
      let current: SkillCategory | null = null;
      for (const [id, element] of sectionRef.current) {
        if (element.getBoundingClientRect().top <= line) current = id as SkillCategory;
      }
      if (current && !jumpRef.current) setActiveSection(current);
      jumpRef.current = false;
    };
    page.addEventListener('scroll', onScroll, { passive: true });
    return () => page.removeEventListener('scroll', onScroll);
  }, [q]);

  const toggleExpanded = (id: SkillCategory) => {
    setExpanded(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAdded = (skill: SkillItem) => {
    setAddedIds(previous => {
      const next = new Set(previous);
      if (next.has(skill.id)) next.delete(skill.id);
      else next.add(skill.id);
      return next;
    });
    toast(
      addedIds.has(skill.id)
        ? t('skills.removed', { name: skill.name })
        : t('skills.addedToast', { name: skill.name })
    );
  };

  return (
    <div className="market-page market-page--skills" data-zone="ZONE_BODY" ref={pageRef}>
      <div className="market-page__inner">
        <header className="market-page__header market-page__header--bar" ref={headerRef}>
          <div className="market-page__heading">
            <h1>{t('nav.skills')}</h1>
            <p>{t('skills.subtitle')}</p>
          </div>
          <div className="market-page__actions">
            <div className={`market-search-switch${searchOpen ? ' is-open' : ''}`}>
              {searchOpen ? (
                <label className="market-page__search market-page__search--grow">
                  <IconSearch size={18} />
                  <input
                    ref={searchRef}
                    type="search"
                    value={query}
                    autoFocus
                    onChange={e => setQuery(e.target.value)}
                    onBlur={() => {
                      if (!query) setSearchOpen(false);
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Escape') {
                        setQuery('');
                        setSearchOpen(false);
                      }
                    }}
                    placeholder={t('skills.search')}
                    aria-label={t('skills.search')}
                  />
                </label>
              ) : (
                <button
                  type="button"
                  className="market-icon-button icon-hover"
                  aria-label={t('skills.search')}
                  title={t('skills.search')}
                  onClick={() => setSearchOpen(true)}
                >
                  <IconSearch size={18} />
                </button>
              )}
            </div>
            <div className="market-page__customize" ref={customizeRef}>
              <button
                type="button"
                className="market-primary-action"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-controls={menuId}
                onClick={() => setMenuOpen(v => !v)}
              >
                <span>{t('skills.customize')}</span>
                <IconChevronDown size={16} />
              </button>
              <PopoverSurface
                open={menuOpen}
                rootRef={customizeRef}
                side="bottom"
                align="end"
                gap={4}
                id={menuId}
                className="market-menu"
                role="menu"
                onDismiss={() => setMenuOpen(false)}
              >
                <button
                  type="button"
                  role="menuitem"
                  className="kimi-dd__item"
                  onClick={() => {
                    setMenuOpen(false);
                    toast(t('skills.uploadSoon'));
                  }}
                >
                  <span className="kimi-dd__item-text">
                    <span className="kimi-dd__item-label">
                      {t('skills.bannerTitle')}
                      <span className="market-menu__badge">{t('skills.menu.beta')}</span>
                    </span>
                    <span className="kimi-dd__item-desc">{t('skills.menu.documentDesc')}</span>
                  </span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="kimi-dd__item"
                  onClick={() => {
                    setMenuOpen(false);
                    toast(t('skills.userSoon'));
                  }}
                >
                  <span className="kimi-dd__item-text">
                    <span className="kimi-dd__item-label">{t('skills.menu.create')}</span>
                    <span className="kimi-dd__item-desc">{t('skills.menu.createDesc')}</span>
                  </span>
                </button>
              </PopoverSurface>
            </div>
          </div>
        </header>

        <section className="market-banner">
          <span className="market-banner__art" aria-hidden>
            <span className="market-banner__sheet">
              <IconFileText size={26} />
            </span>
            <span className="market-banner__spark">
              <IconSpark size={14} />
            </span>
          </span>
          <div className="market-banner__copy">
            <div className="market-banner__title">{t('skills.bannerTitle')}</div>
            <div className="market-banner__desc">{t('skills.bannerBody')}</div>
          </div>
          <button
            type="button"
            className="market-banner__action"
            onClick={() => toast(t('skills.uploadSoon'))}
          >
            {t('skills.upload')}
          </button>
        </section>

        <nav
          className="market-page__cats market-page__cats--bar"
          aria-label={t('skills.cats')}
          ref={catsRef}
        >
          <div className="market-cats__scroll" role="tablist">
            {SKILL_CATEGORIES.map(cat => (
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

        {visibleSections.map(section => {
          const expandedNow = expanded.has(section.id) || Boolean(q);
          const cards = expandedNow ? section.items : section.items.slice(0, SKILL_SECTION_VISIBLE);
          const tail = section.items.slice(SKILL_SECTION_VISIBLE);
          const isEmptyAdded = section.id === 'added' && section.items.length === 0;
          return (
            <section
              key={section.id}
              className={`market-skill-section${isEmptyAdded ? ' is-empty' : ''}`}
              aria-label={t(section.labelKey as MessageKey)}
              ref={element => {
                if (element) sectionRef.current.set(section.id, element);
                else sectionRef.current.delete(section.id);
              }}
            >
              {isEmptyAdded ? null : (
                <h2 className="market-skill-section__title">{t(section.labelKey as MessageKey)}</h2>
              )}
              <div className="market-list market-list--skills">
                {cards.map(skill => {
                  const added = addedIds.has(skill.id);
                  return (
                    <article key={skill.id} className="market-card market-card--skill">
                      <div className="skill-card__main">
                        <span
                          className="skill-card__icon"
                          style={{ color: skill.accent }}
                          aria-hidden
                        >
                          <IconSpark size={22} />
                        </span>
                        <div className="skill-card__content">
                          <div className="skill-card__title-row">
                            <span className="skill-card__title">{skill.name}</span>
                            <button
                              type="button"
                              className={`skill-card__add${added ? ' is-added' : ''}`}
                              onClick={() => toggleAdded(skill)}
                            >
                              {added ? t('skills.added') : t('skills.add')}
                            </button>
                          </div>
                          <div className="skill-card__meta">
                            <span className="skill-card__meta-item">
                              {t('skills.from', { author: skill.author })}
                            </span>
                            <span className="skill-card__meta-divider" aria-hidden />
                            <span className="skill-card__meta-item">
                              {skill.usersLabel} {t('skills.users')}
                            </span>
                          </div>
                        </div>
                      </div>
                      <p className="skill-card__desc">{skill.description}</p>
                    </article>
                  );
                })}
              </div>
              {!expandedNow && tail.length > 0 ? (
                <button
                  type="button"
                  className="market-skill-overflow"
                  onClick={() => toggleExpanded(section.id)}
                >
                  {t('plugins.viewMore')}{' '}
                  {tail
                    .slice(0, 2)
                    .map(skill => skill.name)
                    .join(', ')}
                  {tail.length > 2 ? ` ${t('plugins.andMore', { count: tail.length - 2 })}` : ''}
                </button>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
