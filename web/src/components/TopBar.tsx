import toast from 'react-hot-toast';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import {
  IconChevronDown,
  IconMessage,
  IconPaperclip,
  IconPencil,
  IconPinTop,
  IconShare,
  IconSpark,
  IconTrash,
} from '../icons/kimiStroke';
import { KimiGlyph } from '../icons/kimiNavGlyphs';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import { t } from '../i18n';
import { Button } from './ui/Button';
import { IconButton } from './ui/IconButton';
import { KimiMenu } from './ui/KimiDropdown';

export type ThreadAttachmentItem = {
  id: string;
  filename: string;
  meta: string;
};

export type TopBarProps = {
  /** Product name when empty; ignored when threadTitle is set. */
  title: string;
  /** Active chat title — Kimi header left control. */
  threadTitle?: string | null;
  hasMessages?: boolean;
  attachmentCount?: number;
  /** Thread-scoped files for the paperclip hover shelf (kimi.ai). */
  threadAttachments?: readonly ThreadAttachmentItem[];
  newChatLabel: string;
  collapseLabel: string;
  onNewChat: () => void;
  /**
   * Widget-only: collapse into the host launcher. Omitted in the standalone SPA,
   * where there is no host page to fall back to (kimi.ai has no such control).
   */
  onCollapse?: () => void;
  showNavToggle?: boolean;
  navToggleLabel?: string;
  /** Drawer closed → expand chevron (scaleX -1); open → collapse chevron. */
  navToggleExpand?: boolean;
  onToggleNav?: () => void;
  badges?: readonly string[];
  threadHint?: string | null;
  /** kimi.ai home header pill ("Upgrade your plan"); hidden when omitted. */
  upgradeLabel?: string | null;
  onUpgrade?: () => void;
  /** Full-page views (tasks/history/pricing) carry no header chrome in kimi.ai. */
  bare?: boolean;
  /** Optional page title rendered before the action rail (plugins / full pages). */
  pageTitle?: string | null;
  pageTitleIcon?: ReactNode;
  /** kimi.ai `/plugins` + `/skills` top strip: text tabs with a 2px underline. */
  pageTabs?: readonly { id: string; label: string }[];
  activePageTab?: string;
  onPageTabChange?: (id: string) => void;
  onRenameThread?: () => void;
  /** Active thread is in the «Закреплено» shelf. */
  threadPinned?: boolean;
  onPinThread?: () => void;
  onDeleteThread?: () => void;
  /** Copy contour / thread link (kimi.ai share). */
  onShareThread?: () => void;
  /** Open the composer file picker when the thread has no chips yet. */
  onAddAttachments?: () => void;
  /** Open the «Файлы в чате» right rail (paperclip click). */
  onOpenAttachmentsList?: () => void;
  /** Open a thread file in the right preview pane. */
  onOpenAttachment?: (id: string, filename: string) => void;
};

/**
 * [ZONE_TOP] — Kimi product header: thread title menu + quiet actions.
 */
export function TopBar({
  title,
  threadTitle = null,
  hasMessages = false,
  attachmentCount = 0,
  threadAttachments = [],
  newChatLabel,
  collapseLabel,
  onNewChat: _onNewChat,
  onCollapse,
  showNavToggle = false,
  navToggleLabel,
  navToggleExpand = false,
  onToggleNav,
  badges = [],
  threadHint = null,
  upgradeLabel = null,
  onUpgrade,
  bare = false,
  pageTitle = null,
  pageTitleIcon = null,
  pageTabs = [],
  activePageTab,
  onPageTabChange,
  onRenameThread,
  threadPinned = false,
  onPinThread,
  onDeleteThread,
  onShareThread,
  onAddAttachments,
  onOpenAttachmentsList,
  onOpenAttachment,
}: TopBarProps) {
  const label = (threadTitle?.trim() || newChatLabel).trim();
  const showThreadMenu = hasMessages;
  const shelfFiles = threadAttachments;
  const badgeCount = attachmentCount > 0 ? attachmentCount : shelfFiles.length;
  const showPaperclip = badgeCount > 0 || Boolean(onAddAttachments);
  const [shelfOpen, setShelfOpen] = useState(false);
  const attachRef = useRef<HTMLDivElement>(null);
  const shelfId = useId();

  useEffect(() => {
    if (!shelfOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!attachRef.current?.contains(event.target as Node)) setShelfOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShelfOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [shelfOpen]);

  return (
    <header
      className={`shell-header top-bar${hasMessages ? ' top-bar--chat' : ' top-bar--home'}${
        bare ? ' top-bar--bare' : ''
      }`}
      part="header"
      data-zone="ZONE_TOP"
    >
      <div className="top-bar__leading">
        {pageTitle ? (
          <h1 className="top-bar__page-title">
            {pageTitleIcon}
            <span>{pageTitle}</span>
          </h1>
        ) : null}
        {showNavToggle && onToggleNav ? (
          <Button
            variant="icon"
            className={`top-bar__nav${navToggleExpand ? ' top-bar__nav--expand' : ''}`}
            onClick={onToggleNav}
            aria-label={navToggleLabel ?? 'Menu'}
            title={navToggleLabel}
          >
            {/* kimi LeftBar toggle: chevron enters on hover (same as shelf / stage). */}
            <KimiGlyph name="toggle" size={20} />
          </Button>
        ) : null}

        {pageTabs.length > 0 ? (
          <div className="top-bar__page-tabs" role="tablist">
            {pageTabs.map(tab => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activePageTab === tab.id}
                className={`top-bar__page-tab${activePageTab === tab.id ? ' is-active' : ''}`}
                onClick={() => onPageTabChange?.(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        ) : null}

        {showThreadMenu ? (
          <KimiMenu
            label={label}
            align="start"
            placement="bottom"
            triggerClassName="top-bar__thread-trigger"
            trigger={
              <>
                <span className="top-bar__thread-title" data-name-tip={label}>
                  {label}
                </span>
                <IconChevronDown size={14} className="kimi-dd__chevron" />
              </>
            }
          >
            <button
              type="button"
              className="kimi-dd__item"
              role="menuitem"
              onClick={() => (onRenameThread ? onRenameThread() : toast(t('sidebar.comingSoon')))}
            >
              <IconPencil size={18} />
              <span className="kimi-dd__item-label">{t('thread.rename')}</span>
            </button>
            <button
              type="button"
              className="kimi-dd__item"
              role="menuitem"
              onClick={() => (onPinThread ? onPinThread() : toast(t('sidebar.comingSoon')))}
            >
              <IconPinTop size={18} />
              <span className="kimi-dd__item-label">
                {threadPinned ? t('thread.unpinTop') : t('thread.pinTop')}
              </span>
            </button>
            <button
              type="button"
              className="kimi-dd__item kimi-dd__item--danger"
              role="menuitem"
              onClick={() => (onDeleteThread ? onDeleteThread() : toast(t('sidebar.comingSoon')))}
            >
              <IconTrash size={18} />
              <span className="kimi-dd__item-label">{t('thread.delete')}</span>
            </button>
          </KimiMenu>
        ) : pageTitle ? null : (
          <h1 className="top-bar__title top-bar__title--quiet sr-only">{title}</h1>
        )}

        {badges.map(badge => (
          <span key={badge} className="dev-badge">
            {badge}
          </span>
        ))}
      </div>

      {/* kimi.ai home header centre: promo pill between the two action rails. */}
      {upgradeLabel ? (
        <button
          type="button"
          className="top-bar__promo"
          onClick={onUpgrade}
          aria-label={upgradeLabel}
        >
          <IconSpark size={20} />
          <span>{upgradeLabel}</span>
        </button>
      ) : null}

      <div className="header-actions top-bar__actions">
        {pageTabs.length > 0 ? (
          <IconButton
            className="top-bar__feedback"
            aria-label={t('header.feedback')}
            title={t('header.feedback')}
            onClick={() => toast(t('sidebar.comingSoon'))}
          >
            <IconMessage size={18} />
          </IconButton>
        ) : null}
        {showThreadMenu ? (
          <>
            {/*
              kimi.ai: share + paperclip. Hover → shelf; click → «Файлы в чате» rail.
              Shelf item / chat FileCard → PDF preview pane.
            */}
            <IconButton
              aria-label={t('thread.share')}
              title={t('thread.share')}
              onClick={() => (onShareThread ? onShareThread() : toast(t('sidebar.comingSoon')))}
            >
              <IconShare size={20} />
            </IconButton>
            {showPaperclip ? (
              <div ref={attachRef} className={`top-bar__attach${shelfOpen ? ' is-open' : ''}`}>
                <IconButton
                  aria-label={t('thread.attachments')}
                  title={t('thread.attachments')}
                  aria-haspopup={shelfFiles.length > 0 ? 'menu' : undefined}
                  aria-expanded={shelfFiles.length > 0 ? shelfOpen : undefined}
                  aria-controls={shelfFiles.length > 0 ? shelfId : undefined}
                  onClick={() => {
                    if (shelfFiles.length === 0) {
                      onAddAttachments?.();
                      return;
                    }
                    setShelfOpen(false);
                    onOpenAttachmentsList?.();
                  }}
                >
                  <IconPaperclip size={20} />
                  {badgeCount > 0 ? (
                    <span className="top-bar__badge top-bar__badge--file-count">{badgeCount}</span>
                  ) : null}
                </IconButton>
                {shelfFiles.length > 0 ? (
                  <div
                    id={shelfId}
                    className="top-bar__attach-shelf"
                    role="menu"
                    aria-label={t('thread.attachments')}
                  >
                    <ul className="top-bar__attach-list">
                      {shelfFiles.map(file => (
                        <li key={file.id}>
                          <button
                            type="button"
                            className="top-bar__attach-item"
                            role="menuitem"
                            onClick={() => {
                              setShelfOpen(false);
                              onOpenAttachment?.(file.id, file.filename);
                            }}
                          >
                            <span className="top-bar__attach-icon" aria-hidden>
                              <AttachmentFileIcon
                                kind={attachmentFileKind(file.filename)}
                                size={32}
                              />
                            </span>
                            <span className="top-bar__attach-text">
                              <span className="top-bar__attach-name">{file.filename}</span>
                              <span className="top-bar__attach-meta">{file.meta}</span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
            {threadHint ? <span className="thread-pill">{threadHint}</span> : null}
          </>
        ) : null}
        {/* Widget close — icon only; home omits Log in / Download promo (Kimi parity). */}
        {onCollapse ? (
          <Button
            variant="icon"
            part="close"
            className="top-bar__collapse"
            onClick={onCollapse}
            aria-label={collapseLabel}
            title={collapseLabel}
          >
            <IconChevronDown size={16} />
          </Button>
        ) : null}
      </div>
    </header>
  );
}
