import { useMemo, useRef, useState, type ReactElement } from 'react';
import toast from 'react-hot-toast';
import {
  IconBrandMark,
  IconChevronDown,
  IconChevronRight,
  IconGlobe,
  IconHelp,
  IconInbox,
  IconInfo,
  IconMoreHorizontal,
  IconPencil,
  IconPin,
  IconPinTop,
  IconSettings,
  IconSidebarCustomize,
  IconTrash,
} from '../icons/kimiStroke';
import { KimiGlyph, type KimiGlyphName } from '../icons/kimiNavGlyphs';
import {
  readPinnedThreadIds,
  togglePinnedThreadId,
  writePinnedThreadIds,
} from '../lib/pinnedThreads';
import type { ShellView } from '../lib/shellView';
import { t } from '../i18n';
import { CustomizeSidebarDialog, type SidebarFeature } from './CustomizeSidebarDialog';
import { IconButton } from './ui/IconButton';
import { KimiMenu } from './ui/KimiDropdown';

export type HistoryThreadItem = {
  id: string;
  title: string;
  projectId?: string | null;
  /** ISO timestamp from `GET /sessions` (chat history groups). */
  updatedAt?: string;
};

export type HistoryProjectItem = {
  id: string;
  title: string;
};

export type HistorySidebarProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  threads: readonly HistoryThreadItem[];
  projects: readonly HistoryProjectItem[];
  activeThreadId: string;
  activeView: ShellView;
  onSelectThread: (id: string) => void;
  onNewChat: () => void;
  onNavigate: (view: ShellView | 'stub', stubId?: string) => void;
  /** kimi.ai «Закрепить сверху» — UI shelf pin (not project membership). */
  onPinThreadTop?: (threadId: string) => void;
  onRenameThread?: (threadId: string) => void;
  onDeleteThread?: (threadId: string) => void;
  /** Active project filter (composer pin target + chats shelf scope). */
  activeProjectId?: string | null;
  onSelectProject?: (projectId: string | null) => void;
  onRenameProject?: (projectId: string) => void;
  onPinProject?: (projectId: string) => void;
  onDeleteProject?: (projectId: string) => void;
  /** Ordered thread ids pinned to the top shelf (Закреплено). */
  pinnedThreadIds?: readonly string[];
  userName: string | null;
  offcanvas?: boolean;
  offcanvasHidden?: boolean;
  labels: {
    nav: string;
    newChat: string;
    newChatHint: string;
    collapse: string;
    expand: string;
    history: string;
    projects: string;
    createProject: string;
    projectTitleHint: string;
    renameProject: string;
    pinProject: string;
    deleteProject: string;
    pin: string;
    unpin: string;
    pinnedSection: string;
    profile: string;
    settings: string;
    themeHint: string;
    rename: string;
    delete: string;
    allChats: string;
  };
  onOpenSettings?: () => void;
};

type NavBadge = 'new' | 'beta';

type NavItem = {
  id: string;
  label: string;
  icon: (props: { size?: number }) => ReactElement;
  view?: ShellView;
  stub?: boolean;
  /** kimi.ai product rail chips (3D Make «New», Design «Beta»). */
  badge?: NavBadge;
};

function navBadgeLabel(badge: NavBadge): string {
  return badge === 'new' ? t('nav.badge.new') : t('nav.badge.beta');
}

/** Kimi rail glyphs (extracted 24-grid idle frames) behind the NavItem signature. */
const railGlyph =
  (name: KimiGlyphName) =>
  ({ size = 18 }: { size?: number }) => <KimiGlyph name={name} size={size} />;

/** Rail order + pin set — a UI preference, never product memory (060). */
type SidebarPrefs = { pinned: readonly string[]; order: readonly string[] };

const SIDEBAR_PREFS_KEY = 'palatium:sidebar-prefs';

/** Default rail — cuts drop Inspiration / Code / Work / Platform / 3D / Build / Design. */
const DEFAULT_SIDEBAR_ORDER: readonly string[] = [
  'my',
  'plugins',
  'scheduled',
  'docs',
  'sheets',
  'claw',
  'deep-research',
  'slides',
];

/** Primary rows pinned; `More` holds the remainder (Slides). */
const DEFAULT_SIDEBAR_PINNED: readonly string[] = DEFAULT_SIDEBAR_ORDER.slice(0, 7);

/** Pre-cut defaults — matching prefs migrate; hand-tuned rails stay. */
const LEGACY_SIDEBAR_ORDER: readonly string[] = [
  'my',
  'plugins',
  'scheduled',
  'inspiration',
  'docs',
  'sheets',
  'claw',
  'deep-research',
  'slides',
];
const LEGACY_SIDEBAR_PINNED: readonly string[] = LEGACY_SIDEBAR_ORDER.slice(0, 8);

const sameIds = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((id, index) => id === b[index]);

/** Fixed rail rows stay pinned (Customize cannot unpin). */
const FIXED_RAIL_IDS: ReadonlySet<string> = new Set(['my', 'plugins', 'scheduled']);

function sanitizeSidebarPrefs(raw: unknown): SidebarPrefs | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const candidate = raw as { pinned?: unknown; order?: unknown };
  const rawOrder = candidate.order;
  const rawPinned = candidate.pinned;
  if (!Array.isArray(rawOrder) || !Array.isArray(rawPinned)) return null;
  const known = new Set(DEFAULT_SIDEBAR_ORDER);
  const savedOrder = rawOrder.filter((id): id is string => typeof id === 'string' && known.has(id));
  // New rail entries ship after a user already saved prefs: append, never drop.
  const order = [...savedOrder, ...DEFAULT_SIDEBAR_ORDER.filter(id => !savedOrder.includes(id))];
  const pinned = order.filter(id => rawPinned.includes(id));
  return { pinned, order };
}

function readSidebarPrefs(): SidebarPrefs {
  try {
    const raw = localStorage.getItem(SIDEBAR_PREFS_KEY);
    if (!raw) return { pinned: DEFAULT_SIDEBAR_PINNED, order: DEFAULT_SIDEBAR_ORDER };
    const parsed = sanitizeSidebarPrefs(JSON.parse(raw));
    if (!parsed) return { pinned: DEFAULT_SIDEBAR_PINNED, order: DEFAULT_SIDEBAR_ORDER };
    /* Rail parity migration: only untouched legacy defaults move to the new
       kimi.ai order — a hand-tuned rail is the user's, not ours to reset. */
    if (
      sameIds(parsed.order, LEGACY_SIDEBAR_ORDER) &&
      sameIds(parsed.pinned, LEGACY_SIDEBAR_PINNED)
    ) {
      return { pinned: DEFAULT_SIDEBAR_PINNED, order: DEFAULT_SIDEBAR_ORDER };
    }
    return parsed;
  } catch {
    // Storage disabled (private mode) or corrupt JSON — in-memory defaults are safe.
    return { pinned: DEFAULT_SIDEBAR_PINNED, order: DEFAULT_SIDEBAR_ORDER };
  }
}

function initials(name: string | null, fallback: string): string {
  const raw = (name ?? fallback).trim();
  if (!raw) return 'P';
  const parts = raw.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
  return raw.slice(0, 1).toUpperCase();
}

/**
 * [ZONE_NAV] — product rail + Projects + Chats (Kimi product parity).
 */
export function HistorySidebar({
  collapsed,
  onToggleCollapsed,
  threads,
  projects,
  activeThreadId,
  activeView,
  onSelectThread,
  onNewChat,
  onNavigate,
  onPinThreadTop,
  onRenameThread,
  onDeleteThread,
  activeProjectId = null,
  onSelectProject,
  onRenameProject,
  onPinProject,
  onDeleteProject,
  pinnedThreadIds: pinnedThreadIdsProp,
  userName,
  offcanvas = false,
  offcanvasHidden = false,
  labels,
  onOpenSettings,
}: HistorySidebarProps) {
  const railCollapsed = collapsed && !offcanvas;
  /* kimi.ai collapses «More» until the user opens it (or an overflow view is active). */
  const [moreOpen, setMoreOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [chatsOpen, setChatsOpen] = useState(true);
  const [prefs, setPrefs] = useState<SidebarPrefs>(readSidebarPrefs);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [localPinnedIds, setLocalPinnedIds] = useState<readonly string[]>(readPinnedThreadIds);
  const userAreaRef = useRef<HTMLDivElement>(null);

  const pinnedThreadIds = pinnedThreadIdsProp ?? localPinnedIds;
  const pinnedIdSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds]);
  const threadById = useMemo(() => new Map(threads.map(row => [row.id, row])), [threads]);
  const pinnedThreads = useMemo(
    () =>
      pinnedThreadIds
        .map(id => threadById.get(id))
        .filter((row): row is HistoryThreadItem => row !== undefined),
    [pinnedThreadIds, threadById]
  );
  /* kimi.ai Chats shelf is flat — project folders live under «Проекты», not here. */
  const chatThreads = useMemo(
    () => threads.filter(row => !pinnedIdSet.has(row.id)),
    [threads, pinnedIdSet]
  );

  const pinThreadTop = (threadId: string) => {
    if (onPinThreadTop) {
      onPinThreadTop(threadId);
      return;
    }
    setLocalPinnedIds(prev => {
      const next = togglePinnedThreadId(prev, threadId);
      writePinnedThreadIds(next);
      return next;
    });
  };

  /* Primary rail = kimi.ai; overflow expands inline under More → Collapse. */
  const navItems: NavItem[] = [
    { id: 'my', label: t('nav.myPalatium'), icon: railGlyph('myKimi'), view: 'chat' },
    { id: 'plugins', label: t('nav.plugins'), icon: railGlyph('plugins'), view: 'plugins' },
    {
      id: 'scheduled',
      label: t('nav.scheduled'),
      icon: railGlyph('scheduled'),
      view: 'scheduled',
    },
    { id: 'docs', label: t('nav.docs'), icon: railGlyph('docs'), view: 'docs' },
    { id: 'sheets', label: t('nav.sheets'), icon: railGlyph('sheets'), view: 'sheets' },
    { id: 'claw', label: t('nav.claw'), icon: railGlyph('claw'), view: 'claw' },
    {
      id: 'deep-research',
      label: t('nav.deepResearch'),
      icon: railGlyph('deepResearch'),
      view: 'deep-research',
    },
  ];

  const moreItems: NavItem[] = [
    { id: 'slides', label: t('nav.slides'), icon: railGlyph('slides'), view: 'slides' },
  ];

  /* Pinned features keep their saved order; the rest live under More. */
  const featureById = new Map([...navItems, ...moreItems].map(item => [item.id, item] as const));
  const orderedItems = prefs.order
    .map(id => featureById.get(id))
    .filter((item): item is NavItem => item !== undefined);
  const pinnedSet = new Set(prefs.pinned);
  const pinnedItems = orderedItems.filter(item => pinnedSet.has(item.id));
  const overflowItems = orderedItems.filter(item => !pinnedSet.has(item.id));

  const moreActive = overflowItems.some(i => i.view != null && activeView === i.view);
  /**
   * Skills is the second tab of the Plugins marketplace (`/plugins` ⇄ `/skills`),
   * so the rail entry stays highlighted on both — otherwise `#/skills` leaves
   * the whole rail unselected.
   */
  const railView: ShellView = activeView === 'skills' ? 'plugins' : activeView;
  // Derived, not synced: an active overflow item keeps the group open, and the
  // toggle only adds to that. An effect here re-rendered the whole sidebar.
  const railExpanded = moreOpen || moreActive;

  const activateNav = (item: NavItem) => {
    if (item.view) onNavigate(item.view);
    else {
      onNavigate('stub', item.id);
      toast(t('sidebar.comingSoon'));
    }
  };

  const saveSidebarPrefs = (next: SidebarPrefs) => {
    // The sheet only edits the movable entries: fixed rail rows stay pinned first.
    const fixedOrder = prefs.order.filter(id => FIXED_RAIL_IDS.has(id));
    const merged: SidebarPrefs = {
      order: [...fixedOrder, ...next.order.filter(id => !FIXED_RAIL_IDS.has(id))],
      pinned: [...fixedOrder, ...next.pinned.filter(id => !FIXED_RAIL_IDS.has(id))],
    };
    setPrefs(merged);
    setCustomizeOpen(false);
    try {
      localStorage.setItem(SIDEBAR_PREFS_KEY, JSON.stringify(merged));
    } catch {
      // Private mode / quota — the preference stays session-scoped, never blocks the rail.
    }
  };

  const sidebarFeatures: SidebarFeature[] = [...navItems, ...moreItems]
    .filter(item => !FIXED_RAIL_IDS.has(item.id))
    .map(item => ({
      id: item.id,
      label: item.label,
      icon: item.icon,
    }));

  /* kimi.ai truncates the name with CSS ellipsis (`.user-name`), not in JS. */
  const displayName = userName?.trim() || labels.profile;

  return (
    <aside
      className={[
        /* kimi.ai production classes — keep history-sidebar_* for our styles. */
        'sidebar',
        'next-sidebar',
        'history-sidebar',
        railCollapsed ? 'is-collapsed' : '',
        offcanvas ? 'is-offcanvas-mode' : '',
        offcanvas && offcanvasHidden ? 'is-offcanvas' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-zone="ZONE_NAV"
      aria-label={labels.nav}
      aria-hidden={(offcanvas && offcanvasHidden) || railCollapsed ? true : undefined}
      onPointerUp={event => {
        /* Mouse click leaves :focus on the button; without blur the wash can
           look sticky after the cursor leaves (084 / fine-pointer hover). */
        if (event.pointerType !== 'mouse') return;
        const target = event.target;
        if (!(target instanceof Element)) return;
        const control = target.closest('button, a, [role="button"]');
        if (control instanceof HTMLElement && event.currentTarget.contains(control)) {
          control.blur();
        }
      }}
    >
      <div className="history-sidebar__top">
        <div className="history-sidebar__brand-row">
          {!railCollapsed ? (
            <button
              type="button"
              className="history-sidebar__brand"
              aria-label={t('brand.name')}
              onClick={() => onNavigate('chat')}
            >
              <IconBrandMark size={32} />
            </button>
          ) : null}
          <span className="history-sidebar__collapse-wrap">
            <IconButton
              size="sm"
              className="history-sidebar__collapse"
              onClick={onToggleCollapsed}
              aria-label={railCollapsed ? labels.expand : labels.collapse}
              aria-keyshortcuts="Control+B"
            >
              <KimiGlyph name="toggle" size={24} />
            </IconButton>
            <span className="history-sidebar__tip" role="tooltip">
              {railCollapsed ? labels.expand : labels.collapse}
              <span className="history-sidebar__tip-keys" aria-hidden>
                <kbd className="history-sidebar__tip-key">Ctrl</kbd>
                <kbd className="history-sidebar__tip-key">B</kbd>
              </span>
            </span>
          </span>
        </div>
        {!railCollapsed ? (
          <button
            type="button"
            className="history-sidebar__new icon-hover"
            onClick={onNewChat}
            aria-keyshortcuts="Control+K"
            aria-label={labels.newChat}
          >
            <KimiGlyph name="newChat" size={18} />
            <span>{labels.newChat}</span>
          </button>
        ) : null}
      </div>

      {/* Desktop fold (kimi `.app.fold`): shelf width → 0; no icon rail.
          Expand is `.sidebar-main-trigger` on the stage (ChatShell). */}
      {!railCollapsed ? (
        <div className="history-sidebar__scroll">
          <nav className="history-sidebar__rail" aria-label={labels.nav}>
            {pinnedItems.map(item => {
              const Icon = item.icon;
              const active = item.view != null && railView === item.view;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`history-sidebar__rail-item icon-hover${active ? ' is-active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => activateNav(item)}
                >
                  <Icon size={18} />
                  <span>{item.label}</span>
                  {item.badge ? (
                    <span className={`history-sidebar__rail-badge is-${item.badge}`}>
                      {navBadgeLabel(item.badge)}
                    </span>
                  ) : null}
                </button>
              );
            })}
            <div className="history-sidebar__more-row">
              <button
                type="button"
                className={`history-sidebar__rail-item history-sidebar__rail-item--more icon-hover${
                  moreActive ? ' is-active' : ''
                }`}
                aria-expanded={railExpanded}
                onClick={() => setMoreOpen(v => !v)}
              >
                <KimiGlyph name="collapse" size={20} />
                <span>{railExpanded ? t('nav.collapseMore') : t('nav.more')}</span>
              </button>
              <button
                type="button"
                className="history-sidebar__customize icon-hover"
                aria-label={t('sidebar.customize')}
                title={t('sidebar.customize')}
                onClick={() => setCustomizeOpen(true)}
              >
                <IconSidebarCustomize size={16} />
              </button>
            </div>
            {railExpanded
              ? overflowItems.map(item => {
                  const Icon = item.icon;
                  const active = item.view != null && railView === item.view;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`history-sidebar__rail-item icon-hover${active ? ' is-active' : ''}`}
                      aria-current={active ? 'page' : undefined}
                      onClick={() => activateNav(item)}
                    >
                      <Icon size={18} />
                      <span>{item.label}</span>
                      {item.badge ? (
                        <span className={`history-sidebar__rail-badge is-${item.badge}`}>
                          {navBadgeLabel(item.badge)}
                        </span>
                      ) : null}
                    </button>
                  );
                })
              : null}
          </nav>

          {pinnedThreads.length > 0 ? (
            <div className="history-sidebar__section" aria-label={labels.pinnedSection}>
              <p className="history-sidebar__heading">{labels.pinnedSection}</p>
              <ul className="history-sidebar__list">
                {pinnedThreads.map(thread => {
                  const active = thread.id === activeThreadId && activeView === 'chat';
                  return (
                    <li key={thread.id} className="history-sidebar__thread-row">
                      <button
                        type="button"
                        className={`history-sidebar__item icon-hover${active ? ' is-active' : ''}`}
                        aria-current={active ? 'page' : undefined}
                        title={thread.title}
                        onClick={() => {
                          onNavigate('chat');
                          onSelectThread(thread.id);
                        }}
                      >
                        <span className="history-sidebar__item-title">{thread.title}</span>
                      </button>
                      <KimiMenu
                        label={t('thread.more')}
                        align="end"
                        placement="bottom"
                        triggerClassName="history-sidebar__thread-more"
                        trigger={<IconMoreHorizontal size={14} />}
                      >
                        <button
                          type="button"
                          className="kimi-dd__item"
                          role="menuitem"
                          onClick={() =>
                            onRenameThread
                              ? onRenameThread(thread.id)
                              : toast(t('sidebar.comingSoon'))
                          }
                        >
                          <IconPencil size={18} />
                          <span className="kimi-dd__item-label">{labels.rename}</span>
                        </button>
                        <button
                          type="button"
                          className="kimi-dd__item"
                          role="menuitem"
                          onClick={() => pinThreadTop(thread.id)}
                        >
                          <IconPinTop size={18} />
                          <span className="kimi-dd__item-label">{labels.unpin}</span>
                        </button>
                        <button
                          type="button"
                          className="kimi-dd__item kimi-dd__item--danger"
                          role="menuitem"
                          onClick={() =>
                            onDeleteThread
                              ? onDeleteThread(thread.id)
                              : toast(t('sidebar.comingSoon'))
                          }
                        >
                          <IconTrash size={18} />
                          <span className="kimi-dd__item-label">{labels.delete}</span>
                        </button>
                      </KimiMenu>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          <div className="history-sidebar__section" aria-label={labels.projects}>
            <button
              type="button"
              className="history-sidebar__section-toggle icon-hover"
              aria-expanded={projectsOpen}
              onClick={() => setProjectsOpen(v => !v)}
            >
              <span>{labels.projects}</span>
              {projectsOpen ? (
                <IconChevronDown size={14} className="history-sidebar__section-chevron" />
              ) : (
                <IconChevronRight size={14} className="history-sidebar__section-chevron" />
              )}
            </button>
            {projectsOpen ? (
              <>
                <button
                  type="button"
                  className={`history-sidebar__rail-item icon-hover${
                    activeView === 'project-create' ? ' is-active' : ''
                  }`}
                  onClick={() => onNavigate('project-create')}
                >
                  <KimiGlyph name="newProject" size={18} />
                  <span>{labels.createProject}</span>
                </button>
                {projects.length > 0 ? (
                  <ul className="history-sidebar__list history-sidebar__list--projects">
                    {projects.map(project => {
                      const selected =
                        activeProjectId === project.id &&
                        (activeView === 'project' || activeView === 'chat');
                      return (
                        <li key={project.id} className="history-sidebar__project-item">
                          <button
                            type="button"
                            className={`history-sidebar__project-row icon-hover${
                              selected ? ' is-active' : ''
                            }`}
                            aria-pressed={selected}
                            title={project.title}
                            onClick={() => onSelectProject?.(project.id)}
                          >
                            <KimiGlyph name="folder" size={18} />
                            <span className="history-sidebar__item-title">{project.title}</span>
                          </button>
                          <KimiMenu
                            label={t('thread.more')}
                            align="end"
                            placement="bottom"
                            triggerClassName="history-sidebar__thread-more"
                            trigger={<IconMoreHorizontal size={14} />}
                          >
                            <button
                              type="button"
                              className="kimi-dd__item"
                              role="menuitem"
                              onClick={() => onRenameProject?.(project.id)}
                            >
                              <IconPencil size={18} />
                              <span className="kimi-dd__item-label">{labels.renameProject}</span>
                            </button>
                            <button
                              type="button"
                              className="kimi-dd__item"
                              role="menuitem"
                              onClick={() => onPinProject?.(project.id)}
                            >
                              <IconPin size={16} />
                              <span className="kimi-dd__item-label">{labels.pinProject}</span>
                            </button>
                            <button
                              type="button"
                              className="kimi-dd__item kimi-dd__item--danger"
                              role="menuitem"
                              onClick={() => onDeleteProject?.(project.id)}
                            >
                              <IconTrash size={18} />
                              <span className="kimi-dd__item-label">{labels.deleteProject}</span>
                            </button>
                          </KimiMenu>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </>
            ) : null}
          </div>

          <div className="history-sidebar__section" aria-label={labels.history}>
            <div className="history-sidebar__section-head history-sidebar__section-head--chats">
              <button
                type="button"
                className="history-sidebar__section-toggle icon-hover"
                aria-expanded={chatsOpen}
                onClick={() => setChatsOpen(v => !v)}
              >
                <span>{labels.history}</span>
                {chatsOpen ? (
                  <IconChevronDown size={14} className="history-sidebar__section-chevron" />
                ) : (
                  <IconChevronRight size={14} className="history-sidebar__section-chevron" />
                )}
              </button>
              <button
                type="button"
                className="history-sidebar__link icon-hover"
                onClick={() => onNavigate('history')}
              >
                {labels.allChats}
              </button>
            </div>
            {chatsOpen ? (
              <ul className="history-sidebar__list">
                {chatThreads.map(thread => {
                  const active = thread.id === activeThreadId && activeView === 'chat';
                  return (
                    <li key={thread.id} className="history-sidebar__thread-row">
                      <button
                        type="button"
                        className={`history-sidebar__item icon-hover${active ? ' is-active' : ''}`}
                        aria-current={active ? 'page' : undefined}
                        title={thread.title}
                        onClick={() => {
                          onNavigate('chat');
                          onSelectThread(thread.id);
                        }}
                      >
                        <span className="history-sidebar__item-title">{thread.title}</span>
                      </button>
                      <KimiMenu
                        label={t('thread.more')}
                        align="end"
                        placement="bottom"
                        triggerClassName="history-sidebar__thread-more"
                        trigger={<IconMoreHorizontal size={14} />}
                      >
                        <button
                          type="button"
                          className="kimi-dd__item"
                          role="menuitem"
                          onClick={() =>
                            onRenameThread
                              ? onRenameThread(thread.id)
                              : toast(t('sidebar.comingSoon'))
                          }
                        >
                          <IconPencil size={18} />
                          <span className="kimi-dd__item-label">{labels.rename}</span>
                        </button>
                        <button
                          type="button"
                          className="kimi-dd__item"
                          role="menuitem"
                          onClick={() => pinThreadTop(thread.id)}
                        >
                          <IconPinTop size={18} />
                          <span className="kimi-dd__item-label">{labels.pin}</span>
                        </button>
                        <button
                          type="button"
                          className="kimi-dd__item kimi-dd__item--danger"
                          role="menuitem"
                          onClick={() =>
                            onDeleteThread
                              ? onDeleteThread(thread.id)
                              : toast(t('sidebar.comingSoon'))
                          }
                        >
                          <IconTrash size={18} />
                          <span className="kimi-dd__item-label">{labels.delete}</span>
                        </button>
                      </KimiMenu>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="history-sidebar__foot">
        <div className="history-sidebar__profile-row">
          <div className="history-sidebar__user-area" ref={userAreaRef}>
            <KimiMenu
              label={labels.profile}
              align="start"
              placement="top"
              anchorRef={userAreaRef}
              gap={4}
              triggerClassName={
                railCollapsed ? 'kimi-dd__trigger--icon' : 'kimi-dd__trigger--profile'
              }
              menuClassName="kimi-dd__menu--profile"
              trigger={
                <>
                  <span className="history-sidebar__avatar" aria-hidden>
                    {initials(userName, labels.profile)}
                  </span>
                  {!railCollapsed ? (
                    <span className="history-sidebar__user">{displayName}</span>
                  ) : null}
                </>
              }
            >
              <button
                type="button"
                className="kimi-dd__item"
                role="menuitem"
                onClick={() => toast(t('sidebar.comingSoon'))}
              >
                <IconInfo size={18} />
                <span className="kimi-dd__item-label">{t('sidebar.aboutUs')}</span>
              </button>
              <button
                type="button"
                className="kimi-dd__item"
                role="menuitem"
                onClick={() => toast(t('sidebar.comingSoon'))}
              >
                <IconGlobe size={18} />
                <span className="kimi-dd__item-label">{t('sidebar.language')}</span>
              </button>
              <button
                type="button"
                className="kimi-dd__item"
                role="menuitem"
                onClick={() => toast(t('sidebar.comingSoon'))}
              >
                <IconInbox size={18} />
                <span className="kimi-dd__item-label">{t('sidebar.inbox')}</span>
              </button>
              <button
                type="button"
                className="kimi-dd__item"
                role="menuitem"
                onClick={() => toast(t('sidebar.comingSoon'))}
              >
                <IconHelp size={18} />
                <span className="kimi-dd__item-label">{t('sidebar.getHelp')}</span>
              </button>
              <button
                type="button"
                className="kimi-dd__item"
                role="menuitem"
                onClick={() => onOpenSettings?.()}
              >
                <IconSettings size={18} />
                <span className="kimi-dd__item-label">{labels.settings}</span>
              </button>
            </KimiMenu>
          </div>
        </div>
      </div>

      {customizeOpen ? (
        <CustomizeSidebarDialog
          features={sidebarFeatures}
          value={prefs}
          onClose={() => setCustomizeOpen(false)}
          onSave={saveSidebarPrefs}
        />
      ) : null}
    </aside>
  );
}
