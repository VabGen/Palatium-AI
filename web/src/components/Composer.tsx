import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import toast from 'react-hot-toast';
import { IconArrowUp, IconMic, IconPlus, IconSearch, IconStop, IconX } from '../icons/kimiStroke';
import { INTENT_TEXT_LIMIT } from '../api/client';
import { formatNumber, t } from '../i18n';
import type { ContextLength, ReasoningIntensity } from '../lib/composerModel';
import { ModelIntensityMenu } from './ModelIntensityMenu';
import { PluginsPopover } from './PluginsPopover';
import { ProjectMenu } from './ProjectMenu';
import { SlashPalette, type SlashAction } from './SlashPalette';
import { IconButton } from './ui/IconButton';

export type ComposerAttachmentSlot = ReactNode;

/**
 * kimi.ai `.chat-input-editor-container`: 48px minimum (two 24px lines of the
 * 16px body), grows with the text up to 170px and only then scrolls.
 */
const COMPOSER_INPUT_MIN_HEIGHT = 48;
const COMPOSER_INPUT_MAX_HEIGHT = 170;

export type ComposerProps = {
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  canSend: boolean;
  overLimit: boolean;
  inputLength: number;
  nearLimit: boolean;
  counterClass: string;
  counterLive: 'polite' | 'assertive' | 'off';
  hasMessages: boolean;
  dragActive: boolean;
  onDragOver: (e: DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: DragEvent) => void;
  onPaste: (e: ClipboardEvent<HTMLTextAreaElement>) => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
  composerInputRef: RefObject<HTMLTextAreaElement | null>;
  attachmentAccept: string;
  onFilesSelected: (files: File[]) => void;
  attachmentSlot?: ComposerAttachmentSlot;
  /** Extra tools panel (memory etc.) */
  toolsSlot?: ReactNode;
  projectId: string;
  projects: readonly { id: string; title: string }[];
  onProjectChange: (id: string) => void;
  onRequestCreateProject?: () => void;
  intensity: ReasoningIntensity;
  contextLength: ContextLength;
  onIntensityChange: (value: ReasoningIntensity) => void;
  onContextLengthChange: (value: ContextLength) => void;
  onOpenPluginsPage: () => void;
  onSlashAction: (action: SlashAction) => void;
  /** kimi.ai product routes show the active tool («Docs», «Slides», …) next to `+`. */
  productMode?: { label: string; icon: ReactNode };
  /** Dismiss product skill chip (return to home chat). */
  onExitProductMode?: () => void;
  /** Publisher shortcuts — stay inside sticky `#chat-box` (kimi.ai). */
  productChips?: ReactNode;
  /**
   * Home-landing tail below `#chat-box` (Explore / Featured cases / Product
   * showcase). Must not live inside the sticky box or `position:absolute`
   * pins it to the capsule instead of the stage edge.
   */
  landingTail?: ReactNode;
  showEmptyChrome?: boolean;
  /** Home / mode strip under capsule. */
  showToolBar?: boolean;
  /** Deep Research landing: mode chip + detached options tray. */
  deepResearchMode?: boolean;
  /** Dismiss Deep Research mode chip (return to home). */
  onExitDeepResearch?: () => void;
  /** Product landing override (Slides / Docs / Sheets / … placeholders). */
  placeholderOverride?: string;
  /** kimi.ai in-thread web-search preference for the `+` nested panel. */
  webSearchMode?: 'auto' | 'off';
};

/**
 * [ZONE_FOOTER] — Kimi-style composer capsule (slash, model lane, project/plugins bar).
 */
export function Composer({
  input,
  onInputChange,
  onSubmit,
  onStop,
  busy,
  canSend,
  overLimit,
  inputLength,
  nearLimit,
  counterClass,
  counterLive,
  hasMessages,
  dragActive,
  onDragOver,
  onDragLeave,
  onDrop,
  onPaste,
  fileInputRef,
  composerInputRef,
  attachmentAccept,
  onFilesSelected,
  attachmentSlot,
  toolsSlot,
  projectId,
  projects,
  onProjectChange,
  onRequestCreateProject,
  intensity,
  contextLength,
  onIntensityChange,
  onContextLengthChange,
  onOpenPluginsPage,
  onSlashAction,
  productMode,
  onExitProductMode,
  productChips,
  landingTail,
  showEmptyChrome = false,
  showToolBar,
  deepResearchMode = false,
  onExitDeepResearch,
  placeholderOverride,
  webSearchMode = 'auto',
}: ComposerProps) {
  const [toolsOpen, setToolsOpen] = useState(false);
  /** Bumps SlashPalette remount so nested «Web search» resets on each `+` open. */
  const [slashEpoch, setSlashEpoch] = useState(0);
  /** Whole card: the tray chips hang off it (kept open on hover). */
  const capsuleRef = useRef<HTMLDivElement>(null);
  /** White editor card: kimi.ai hangs the toolkit panel off this bottom edge. */
  const formRef = useRef<HTMLFormElement>(null);
  const toolsButtonRef = useRef<HTMLButtonElement>(null);
  const slashTyped = input.trimStart().startsWith('/');
  const slashOpen = toolsOpen || slashTyped;
  const showBar = showToolBar ?? (!hasMessages || showEmptyChrome);
  const placeholder = busy
    ? t('composer.placeholderQueue')
    : hasMessages
      ? t('composer.placeholderChat')
      : deepResearchMode
        ? t('composer.placeholderDeepResearch')
        : (placeholderOverride ?? t('composer.placeholderHome'));

  const closeTools = () => setToolsOpen(false);

  /**
   * Auto-grow parity with kimi.ai: the editor keeps a 48px floor, expands with
   * each wrapped line and caps at 170px — past the cap the textarea scrolls.
   */
  useEffect(() => {
    const el = composerInputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const next = Math.min(
      Math.max(el.scrollHeight, COMPOSER_INPUT_MIN_HEIGHT),
      COMPOSER_INPUT_MAX_HEIGHT
    );
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > COMPOSER_INPUT_MAX_HEIGHT ? 'auto' : 'hidden';
  }, [input, composerInputRef]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (busy && onStop) {
      onStop();
      return;
    }
    onSubmit();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!busy) onSubmit();
    }
    if (e.key === 'Escape' && slashOpen) {
      closeTools();
      if (slashTyped) onInputChange('');
    }
  };

  const handleSlash = (action: SlashAction) => {
    if (action.kind === 'webSearch') {
      // Keep the nested panel open until the caller applies the preference.
      onSlashAction(action);
      closeTools();
      onInputChange(input.replace(/^\s*\/\S*/, '').trimStart());
      return;
    }
    closeTools();
    onInputChange(input.replace(/^\s*\/\S*/, '').trimStart());
    if (action.kind === 'attach') {
      fileInputRef.current?.click();
      return;
    }
    if (action.kind === 'plugins') {
      onOpenPluginsPage();
      return;
    }
    onSlashAction(action);
  };

  const chatBox = (
    <>
      <div
        ref={capsuleRef}
        className={`composer-capsule${showBar ? ' composer-capsule--bar' : ''}${
          deepResearchMode || showEmptyChrome ? ' composer-capsule--landing' : ''
        }${deepResearchMode ? ' composer-capsule--deep' : ''}`}
      >
        {toolsSlot}
        <form ref={formRef} className="composer-capsule__form" onSubmit={handleSubmit}>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            accept={attachmentAccept}
            onChange={e => {
              onFilesSelected(Array.from(e.target.files ?? []));
              e.target.value = '';
            }}
          />
          {/* kimi.ai: file cards live inside the white editor card, above the textarea. */}
          {attachmentSlot}
          <textarea
            ref={composerInputRef}
            value={input}
            onChange={e => onInputChange(e.target.value)}
            onPaste={onPaste}
            placeholder={placeholder}
            rows={1}
            onKeyDown={handleKeyDown}
            aria-describedby="composer-counter"
            className={
              overLimit ? 'composer-textarea composer-textarea--over' : 'composer-textarea'
            }
          />
          <div className="composer-capsule__toolbar">
            <div className="composer-capsule__leading">
              <IconButton
                ref={toolsButtonRef}
                className={`composer-capsule__plus${toolsOpen ? ' is-open' : ''}`}
                aria-label={toolsOpen ? t('composer.toolsClose') : t('composer.tools')}
                title={toolsOpen ? t('composer.toolsClose') : t('composer.tools')}
                aria-expanded={slashOpen}
                disabled={busy}
                onClick={() =>
                  setToolsOpen(v => {
                    if (!v) setSlashEpoch(epoch => epoch + 1);
                    return !v;
                  })
                }
              >
                {toolsOpen ? <IconX size={18} /> : <IconPlus size={18} />}
              </IconButton>
              {deepResearchMode ? (
                <button
                  type="button"
                  className="composer-mode-chip"
                  aria-current="true"
                  aria-label={t('composer.exitDeepResearch')}
                  onClick={() => onExitDeepResearch?.()}
                >
                  <IconSearch size={18} />
                  <span>{t('composer.deepResearchMode')}</span>
                  <IconX size={12} className="composer-mode-chip__close" />
                </button>
              ) : null}
              {productMode ? (
                <button
                  type="button"
                  className="composer-product-chip"
                  aria-pressed="true"
                  aria-label={t('composer.exitProductMode', { name: productMode.label })}
                  onClick={() => onExitProductMode?.()}
                >
                  {productMode.icon}
                  <span>{productMode.label}</span>
                  <IconX size={12} className="composer-product-chip__close" />
                </button>
              ) : null}
            </div>
            <div className="composer-capsule__trailing">
              <ModelIntensityMenu
                intensity={intensity}
                contextLength={contextLength}
                onIntensityChange={onIntensityChange}
                onContextLengthChange={onContextLengthChange}
                disabled={busy}
              />
              <IconButton
                aria-label={t('composer.mic')}
                disabled={busy}
                onClick={() => toast(t('composer.micSoon'))}
              >
                <IconMic size={18} />
              </IconButton>
              {busy ? (
                <IconButton
                  tone="solid"
                  className="send-btn is-stop"
                  aria-label={t('composer.stop')}
                  onClick={() => onStop?.()}
                >
                  <IconStop size={14} />
                </IconButton>
              ) : (
                <IconButton
                  type="submit"
                  tone={canSend ? 'solid' : 'soft'}
                  className="send-btn"
                  disabled={!canSend}
                  aria-label={t('composer.send')}
                  title={
                    overLimit
                      ? t('composer.overLimitTitle', {
                          used: formatNumber(inputLength),
                          limit: formatNumber(INTENT_TEXT_LIMIT),
                        })
                      : undefined
                  }
                >
                  <IconArrowUp size={28} />
                </IconButton>
              )}
            </div>
          </div>
        </form>

        <SlashPalette
          key={slashEpoch}
          open={slashOpen}
          anchorRef={formRef}
          triggerRef={toolsButtonRef}
          keepOpenRef={capsuleRef}
          onDismiss={closeTools}
          variant={hasMessages ? 'chat' : 'home'}
          webSearchMode={webSearchMode}
          labels={{
            addFiles: t('slash.addFiles'),
            plugins: t('slash.plugins'),
            pluginsDesc: t('slash.pluginsDesc'),
            skills: t('slash.skills'),
            skillsDesc: t('slash.skillsDesc'),
            goal: t('slash.goal'),
            goalDesc: t('slash.goalDesc'),
            webSearch: t('slash.webSearch'),
            webSearchDesc: t('slash.webSearchDesc'),
            webSearchBack: t('slash.webSearchBack'),
            webSearchAuto: t('slash.webSearchAuto'),
            webSearchAutoDesc: t('slash.webSearchAutoDesc'),
            webSearchOff: t('slash.webSearchOff'),
            webSearchOffDesc: t('slash.webSearchOffDesc'),
          }}
          onSelect={handleSlash}
        />

        {showBar ? (
          <div
            className={`composer-capsule__bar${
              deepResearchMode || showEmptyChrome ? ' composer-capsule__bar--tray' : ''
            }`}
          >
            <ProjectMenu
              projects={projects}
              projectId={projectId}
              onSelect={onProjectChange}
              onRequestCreate={onRequestCreateProject}
              disabled={busy}
            />
            <PluginsPopover onManage={onOpenPluginsPage} disabled={busy} />
          </div>
        ) : null}
      </div>

      {productChips}
    </>
  );

  return (
    <div
      className={`composer-stack composer-stack--product${dragActive ? ' is-dragover' : ''}${
        showEmptyChrome ? ' is-home' : ''
      }${deepResearchMode ? ' is-deep-research' : ''}`}
      part="composer"
      data-zone="ZONE_FOOTER"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {showEmptyChrome ? (
        <div id="chat-box" className="chat-box">
          {chatBox}
        </div>
      ) : (
        chatBox
      )}
      {landingTail}
      {(nearLimit || overLimit) && (
        <div
          id="composer-counter"
          className={counterClass}
          aria-live={counterLive}
          aria-atomic="true"
        >
          {t('composer.counter', {
            used: formatNumber(inputLength),
            limit: formatNumber(INTENT_TEXT_LIMIT),
          })}
        </div>
      )}
    </div>
  );
}
