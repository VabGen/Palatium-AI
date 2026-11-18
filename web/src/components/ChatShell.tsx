import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ClipboardEvent, CSSProperties, ReactElement } from 'react';
import toast from 'react-hot-toast';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import { IconChevronDown, IconLoader, IconX } from '../icons/kimiStroke';
import { AnswerFileCards } from './AnswerFileCards';
import { KimiGlyph } from '../icons/kimiNavGlyphs';
import { ProductChips, type ProductChipItem } from './ProductChips';
import { ProductShowcase } from './ProductShowcase';
import { IconButton } from './ui/IconButton';
import {
  INTENT_TEXT_LIMIT,
  deleteAttachment,
  downloadDocumentPdf,
  ensureAccessToken,
  fetchDialogTurns,
  archiveSession,
  createProject,
  deleteProject,
  listProjects,
  listSessions,
  processIntentStream,
  renameProject,
  renameSession,
  sendFeedback,
  truncateDialogTurns,
} from '../api/client';
import {
  keepCountBeforeEdit,
  keepCountBeforeRegenerate,
  messagesKeptBeforeEdit,
  messagesKeptForRegenerate,
} from '../lib/turnRewind';
import { shareAnswerText } from '../lib/shareAnswer';
import { readSettingsPrefs } from '../lib/settingsPrefs';
import type {
  ContentBlock,
  ContentDocument,
  DocumentRevision,
  FormatterTaskResult,
  HITLCardView,
  ProjectSummary,
} from '../types/contentDocument';
import { isDocumentRevision } from '../lib/revision';
import { fieldsFromFormatterResult, hydratePendingHitlCards } from '../lib/hitl';
import { hydrateUserTurn } from '../lib/hydrateUserTurn';
import { looksLikeExclusiveMenu } from '../lib/exclusiveMenu';
import { markFirstVisualStart, measureFirstVisual } from '../lib/firstVisual';
import { pendingPhaseForNode } from '../lib/pendingOrb';
import { useStreamAnnouncer } from '../lib/useStreamAnnouncer';
import { isArtifactWorthy } from '../lib/artifactDocument';
import {
  buildDialogueNavEntries,
  dialogueTurnDomId,
  shouldShowDialogueNav,
} from '../lib/dialogueNav';
import { ArtifactPane } from './ArtifactPane';
import { BrandWordmark } from './BrandWordmark';
import { CitationSources } from './CitationSources';
import { DialogueNav } from './DialogueNav';
import { FilePreviewPane } from './FilePreviewPane';
import { SideConsoleResizer } from './SideConsoleResizer';
import {
  clampSideConsoleWidthPct,
  readSideConsoleWidthPct,
  SIDE_CONSOLE_WIDTH_DEFAULT,
  writeSideConsoleWidthPct,
} from '../lib/sideConsoleWidth';
import { initialShellDensity, shellDensityFromWidth } from '../lib/shellDensity';
import { KimiDialog } from './KimiDialog';
import { LiveAnnouncer } from './LiveAnnouncer';
import { StreamMarkdownPreview } from './StreamMarkdownPreview';
import { connectSessionSocket, startSessionSocketPing } from '../lib/sessionSocket';
import { formatNumber, getI18nLocale, t } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import {
  setPanelOpen,
  startNewThread as startNewThreadInRuntime,
  switchThread as switchThreadInRuntime,
} from '../runtime/store';
import { useAssistantRuntime } from '../runtime/useRuntime';
import {
  resolveComposerModeFromUi,
  resolveWireModelId,
  type ContextLength,
  type ReasoningIntensity,
} from '../lib/composerModel';
import {
  readPinnedThreadIds,
  togglePinnedThreadId,
  writePinnedThreadIds,
} from '../lib/pinnedThreads';
import { cleanHistorySnippet } from '../lib/historyPreview';
import { mapSessionsToShelf, mergeShelfWithLiveThread } from '../lib/sessionShelf';
import {
  hashForProject,
  hashForProjectCreate,
  hashForSettingsSection,
  hashForShellView,
  isChatSurface,
  isHomeView,
  projectIdFromHash,
  settingsSectionFromHash,
  shellViewFromHash,
  type SettingsSectionId,
  type ShellView,
} from '../lib/shellView';
import { SettingsPage } from './SettingsPage';
import {
  ATTACHMENT_ACCEPT,
  MAX_ATTACHMENTS_PER_TURN,
  MAX_ATTACHMENT_LABEL,
  attachmentChipMeta,
  attachmentDisplayName,
  attachmentTypeLabel,
  attachmentRefusalReason,
  createPastedTextFile,
  displaySourceRefs,
  sourceRefFingerprint,
  refusalLabel,
  revokeAttachmentPreview,
  revokeAttachmentPreviews,
  shouldAutoAttachText,
  uploadAttachment,
} from '../lib/attachments';
import type { AttachmentDraft } from '../lib/attachments';
import { BlockRenderer } from './BlockRenderer';
import { HitlCards, type HitlResolvedEvent } from './HitlCards';
import { MemoryActions } from './MemoryActions';
import { MessageList } from './MessageList';
import { RevisionNote } from './RevisionNote';
import { ThinkingIndicator } from './ThinkingIndicator';
import { TopBar } from './TopBar';
import { HistorySidebar, type HistoryThreadItem } from './HistorySidebar';
import type { ComposerMode } from './ComposerModePills';
import { Composer } from './Composer';
import { FeaturedResearchCases } from './FeaturedResearchCases';
import {
  AssistantAvatar,
  MessageActions,
  UserAttachmentCard,
  UserMessageActions,
} from './MessageChrome';

const PluginsPage = lazy(async () => {
  const mod = await import('./PluginsPage');
  return { default: mod.PluginsPage };
});
const SkillsPage = lazy(async () => {
  const mod = await import('./SkillsPage');
  return { default: mod.SkillsPage };
});
const ScheduledTasksPage = lazy(async () => {
  const mod = await import('./ScheduledTasksPage');
  return { default: mod.ScheduledTasksPage };
});
const ChatHistoryPage = lazy(async () => {
  const mod = await import('./ChatHistoryPage');
  return { default: mod.ChatHistoryPage };
});
const CreateProjectPage = lazy(async () => {
  const mod = await import('./CreateProjectPage');
  return { default: mod.CreateProjectPage };
});
const ProjectWorkspacePage = lazy(async () => {
  const mod = await import('./ProjectWorkspacePage');
  return { default: mod.ProjectWorkspacePage };
});
/** Product landings reuse the home stage with their own composer placeholder. */
function productPlaceholder(view: ShellView, projectTitle?: string): string | undefined {
  if (view === 'project' && projectTitle) {
    return t('project.workspace.composer', { title: projectTitle });
  }
  switch (view) {
    case 'slides':
      return t('product.placeholder.slides');
    case 'docs':
      return t('product.placeholder.docs');
    case 'sheets':
      return t('product.placeholder.sheets');
    case 'claw':
      return t('product.placeholder.claw');
    default:
      return undefined;
  }
}

/** Views whose page header replaces the shell top bar (nav lives in the sidebar). */
const FULL_PAGE_VIEWS: readonly ShellView[] = ['scheduled', 'history', 'project-create'];

/**
 * Home publisher shortcuts behave exactly like kimi.ai: each chip is a link to
 * the matching product landing (`/make3d`, `/slides`, …), not a prompt seed.
 */
const CHIP_VIEWS: Readonly<Record<string, ShellView>> = {
  slides: 'slides',
  deep: 'deep-research',
  docs: 'docs',
  sheets: 'sheets',
};

/**
 * Composer tool chip on product routes — active tool («Docs», «Slides», …)
 * sits right after the `+` button.
 */
const PRODUCT_MODES: Partial<Record<ShellView, { labelKey: MessageKey; icon: ReactElement }>> = {
  docs: { labelKey: 'nav.docs', icon: <KimiGlyph name="docs" size={18} /> },
  sheets: { labelKey: 'nav.sheets', icon: <KimiGlyph name="sheets" size={18} /> },
  slides: { labelKey: 'nav.slides', icon: <KimiGlyph name="slides" size={18} /> },
  claw: { labelKey: 'nav.claw', icon: <KimiGlyph name="claw" size={18} /> },
};

/** Wordmark on home + deep-research; other product routes keep the slot empty. */
const LOGO_VIEWS: ReadonlySet<ShellView> = new Set<ShellView>(['chat', 'deep-research']);

/**
 * Порог, за которым счётчик символов начинает подсвечиваться предупреждающе.
 */
const COUNTER_WARN_THRESHOLD = 2_000;

type AssistantChatMessage = {
  id: string;
  role: 'assistant';
  document: ContentDocument | null;
  /**
   * Diff против предыдущего ответа (W7b). Индексы внутри `revision` адресуют блоки
   * `document`, поэтому при любой замене документа ревизия сбрасывается — иначе
   * подсветка указала бы на чужой блок.
   */
  revision?: DocumentRevision | null;
  hitlCards?: HITLCardView[];
  _requiresReview?: boolean;
  _pendingReview?: boolean;
  _feedbackLike?: boolean;
  _feedbackDislike?: boolean;
  _feedbackSending?: boolean;
  _regenerating?: boolean;
  /** True while SSE preview fills this bubble (stable key until document lands). */
  _streaming?: boolean;
  error?: string;
  status?: string;
};

type ChatMessage =
  | {
      id: string;
      role: 'user';
      text: string;
      /** Ids actually injected into that turn, so a regenerate repeats the same context. */
      attachmentIds?: string[];
      attachmentNames?: string[];
    }
  | AssistantChatMessage;

function isContentDocument(value: unknown): value is ContentDocument {
  return (
    typeof value === 'object' &&
    value !== null &&
    'schema_version' in value &&
    'blocks' in value &&
    Array.isArray((value as ContentDocument).blocks)
  );
}

function isHitlCardView(value: unknown): value is HITLCardView {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as HITLCardView).card_id === 'string' &&
    Array.isArray((value as HITLCardView).options)
  );
}

function textAsDocument(text: string): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [{ type: 'paragraph', text }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

function parseAssistantPayload(
  payload: unknown,
  fallbackText: string
): {
  document: ContentDocument;
  requiresReview: boolean;
  hitlCards: HITLCardView[];
  revision: DocumentRevision | null;
} {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const requiresReview = Boolean(record.requires_review) || false;
    const rawCards = Array.isArray(record.hitl_cards)
      ? record.hitl_cards.filter(isHitlCardView)
      : [];
    const revision = isDocumentRevision(record.revision) ? record.revision : null;
    if (isContentDocument(record.document)) {
      return { document: record.document, requiresReview, hitlCards: rawCards, revision };
    }
    if (isContentDocument(payload)) {
      return { document: payload, requiresReview, hitlCards: rawCards, revision };
    }
  }
  return {
    document: textAsDocument(fallbackText),
    requiresReview: false,
    hitlCards: [],
    revision: null,
  };
}

function getDocumentPlainText(doc: ContentDocument): string {
  const parts: string[] = [];
  if (doc.title) parts.push(doc.title);
  for (const block of doc.blocks) {
    switch (block.type) {
      case 'heading':
      case 'paragraph':
      case 'callout':
        if ('text' in block && block.text) parts.push(block.text);
        else if ('body' in block && block.body) parts.push(block.body);
        break;
      case 'code':
        if ('content' in block && block.content) parts.push(block.content);
        break;
      case 'formula':
        if ('latex' in block && block.latex) parts.push(block.latex);
        break;
      case 'widget':
        if ('title' in block && block.title) parts.push(block.title);
        break;
      case 'list':
        for (const item of block.items) {
          if (item.text) parts.push(item.text);
        }
        break;
      case 'steps':
        for (const step of block.items) {
          if (step.title) parts.push(step.title);
          if (step.body) parts.push(step.body);
        }
        break;
      case 'kv':
        for (const kv of block.items) {
          if (kv.label) parts.push(`${kv.label}: ${kv.value}`);
        }
        break;
      case 'table':
        for (const row of block.rows) {
          parts.push(row.join(' | '));
        }
        break;
      case 'chart':
        if (block.title) parts.push(block.title);
        parts.push(block.labels.join(', '));
        break;
      default:
        break;
    }
  }
  return parts.join('\n').trim() || '(empty)';
}

function buildAssistantMessage(result: FormatterTaskResult, id?: string): AssistantChatMessage {
  return {
    id: id ?? crypto.randomUUID(),
    role: 'assistant',
    ...fieldsFromFormatterResult(result),
  };
}

export function ChatShell() {
  // Идентификаторы приходят из runtime: в embed — из SedContext (`user.id`,
  // `scope.tenantId`), автономно — из in-memory значений сессии. Storage запрещён.
  const { userId, orgId, threadId, hostStatus, userName, mode } = useAssistantRuntime();
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [devMode, setDevMode] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [projectId, setProjectId] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => initialShellDensity().narrow);
  const [isNarrowShell, setIsNarrowShell] = useState(() => initialShellDensity().narrow);
  /** ≤480px panel (SED right rail) — denser type/padding; driven by shell width. */
  const [isCompactShell, setIsCompactShell] = useState(() => initialShellDensity().compact);
  const shellRef = useRef<HTMLDivElement>(null);
  const [modeIntent, setModeIntent] = useState<ComposerMode | null>(null);
  /** kimi.ai `+` → Web search nested panel (Autosearch default). */
  const [webSearchPref, setWebSearchPref] = useState<'auto' | 'off'>('auto');
  const [intensity, setIntensity] = useState<ReasoningIntensity>('standard');
  const [contextLength, setContextLength] = useState<ContextLength>('standard');
  const [shellView, setShellView] = useState<ShellView>(() =>
    typeof window !== 'undefined' ? shellViewFromHash(window.location.hash) : 'chat'
  );
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>(() =>
    typeof window !== 'undefined' ? settingsSectionFromHash(window.location.hash) : 'account'
  );
  /** P1b: durable history shelf from `GET /sessions` (titles; turns hydrate by threadId). */
  const [sessionShelf, setSessionShelf] = useState<HistoryThreadItem[]>([]);
  /** P2: durable Projects for pin + attachment KB scope. */
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  /** kimi.ai «Закрепить сверху» — UI shelf prefs (localStorage), not project membership. */
  const [pinnedThreadIds, setPinnedThreadIds] = useState<readonly string[]>(readPinnedThreadIds);
  const [artifactMessageId, setArtifactMessageId] = useState<string | null>(null);
  /**
   * kimi.ai right-rail: «Файлы в чате» list or binary preview
   * (mutually exclusive with ArtifactPane).
   */
  const [filesRail, setFilesRail] = useState<
    null | { mode: 'list' } | { mode: 'preview'; id: string; filename: string; page?: number }
  >(null);
  /** kimi dual-pane: user-resizable side-console width (% of workspace). */
  const [sideConsoleWidthPct, setSideConsoleWidthPct] = useState(readSideConsoleWidthPct);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const canResizeSideConsole = Boolean(
    (artifactMessageId || filesRail) && filesRail?.mode !== 'list'
  );

  // Wire model reserved for future explicit model routing; intensity+chip map composer_mode today.
  void resolveWireModelId(intensity);
  const effectiveComposerMode = resolveComposerModeFromUi(intensity, modeIntent);

  /*
   * Density from `.shell` width (not viewport): SED host opens a ~400px right
   * panel inside a wide desktop — matchMedia(viewport) would never densify.
   * Re-bind when leaving settings (shell unmounts during that view).
   */
  useEffect(() => {
    if (shellView === 'settings') return;
    const node = shellRef.current;
    if (!node) return;

    let wasNarrow = shellDensityFromWidth(node.getBoundingClientRect().width).narrow;

    const apply = (width: number) => {
      const next = shellDensityFromWidth(width);
      setIsNarrowShell(next.narrow);
      setIsCompactShell(next.compact);
      // Collapse only on transition into narrow — don't fight an open drawer.
      if (next.narrow && !wasNarrow) setSidebarCollapsed(true);
      wasNarrow = next.narrow;
    };

    apply(node.getBoundingClientRect().width);

    if (typeof ResizeObserver === 'undefined') {
      const onResize = () => apply(node.getBoundingClientRect().width);
      window.addEventListener('resize', onResize);
      return () => window.removeEventListener('resize', onResize);
    }

    const ro = new ResizeObserver(entries => {
      const entry = entries[0];
      if (!entry) return;
      apply(entry.contentRect.width);
    });
    ro.observe(node);
    return () => ro.disconnect();
  }, [shellView]);

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash;
      setShellView(shellViewFromHash(hash));
      setSettingsSection(settingsSectionFromHash(hash));
      const fromHash = projectIdFromHash(hash);
      if (fromHash) setProjectId(fromHash);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const navigateSettings = useCallback((section: SettingsSectionId) => {
    setSettingsSection(section);
    if (typeof window !== 'undefined') {
      const next = hashForSettingsSection(section);
      if (window.location.hash !== next) {
        window.history.replaceState(null, '', next);
      }
    }
  }, []);

  const collapseNavIfNarrow = useCallback(() => {
    const width = shellRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    if (shellDensityFromWidth(width).narrow) {
      setSidebarCollapsed(true);
    }
  }, []);

  const navigateShell = useCallback(
    (view: ShellView | 'stub', _stubId?: string) => {
      if (view === 'stub') return;
      setShellView(view);
      if (typeof window !== 'undefined') {
        const next = view === 'project-create' ? hashForProjectCreate() : hashForShellView(view);
        if (window.location.hash !== next) {
          window.history.replaceState(null, '', next);
        }
      }
      collapseNavIfNarrow();
    },
    [collapseNavIfNarrow]
  );

  const navigateProject = useCallback(
    (id: string) => {
      setProjectId(id);
      setShellView('project');
      if (typeof window !== 'undefined') {
        const next = hashForProject(id);
        if (window.location.hash !== next) {
          window.history.replaceState(null, '', next);
        }
      }
      collapseNavIfNarrow();
    },
    [collapseNavIfNarrow]
  );

  const handleNewThreadRef = useRef<(() => void) | null>(null);

  const [renameTarget, setRenameTarget] = useState<{ id: string; title: string } | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<{ id: string; title: string } | null>(null);
  const [bulkArchive, setBulkArchive] = useState<readonly { id: string; title: string }[] | null>(
    null
  );
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [projectRename, setProjectRename] = useState<{ id: string; title: string } | null>(null);
  const [projectRenameDraft, setProjectRenameDraft] = useState('');
  const [projectRenameBusy, setProjectRenameBusy] = useState(false);
  const [projectDelete, setProjectDelete] = useState<{ id: string; title: string } | null>(null);
  const [projectDeleteBusy, setProjectDeleteBusy] = useState(false);

  const refreshSessionShelf = useCallback(async () => {
    try {
      const rows = await listSessions(24, 0, userId, orgId);
      setSessionShelf(mapSessionsToShelf(rows, t('sidebar.untitled')));
    } catch (err) {
      console.warn('Session shelf refresh failed:', err);
    }
  }, [orgId, userId]);

  const refreshProjects = useCallback(async () => {
    try {
      const rows = await listProjects(50, 0, userId, orgId);
      setProjects(rows);
    } catch (err) {
      console.warn('Projects refresh failed:', err);
    }
  }, [orgId, userId]);

  useEffect(() => {
    void refreshSessionShelf();
    void refreshProjects();
  }, [refreshProjects, refreshSessionShelf]);

  const handleCreateProject = useCallback(
    async (title: string) => {
      try {
        const created = await createProject(title, userId, orgId);
        setProjects(prev => [created, ...prev.filter(p => p.id !== created.id)]);
        navigateProject(created.id);
      } catch (err) {
        /* Standalone without `/projects` still completes the kimi create → workspace chain. */
        console.warn('Create project failed; using local workspace:', err);
        const now = new Date().toISOString();
        const local: ProjectSummary = {
          id: crypto.randomUUID(),
          user_id: userId ?? 'local',
          title,
          created_at: now,
          updated_at: now,
        };
        setProjects(prev => [local, ...prev.filter(p => p.id !== local.id)]);
        navigateProject(local.id);
      }
    },
    [navigateProject, orgId, userId]
  );

  const handlePinThreadTop = useCallback((targetThreadId: string) => {
    setPinnedThreadIds(prev => {
      const next = togglePinnedThreadId(prev, targetThreadId);
      writePinnedThreadIds(next);
      return next;
    });
  }, []);

  const [dragActive, setDragActive] = useState(false);
  /** Progressive SSE preview — always GFM via StreamMarkdownPreview (Path C). */
  const [streamPreview, setStreamPreview] = useState('');
  /**
   * Последний `hop` из SSE — id узла графа, который сейчас работает.
   * Источник правды для анимации ожидания: `null` до первого события.
   */
  const [pendingNode, setPendingNode] = useState<string | null>(null);
  const pendingPhase = pendingPhaseForNode(pendingNode);
  /**
   * Канал озвучивания (084, W2). Лента — `role="log"` с `aria-live="off"`, поэтому
   * прогресс объявляется отдельно: ровно один раз на закрытый блок.
   */
  const [a11yAnnouncement, a11y] = useStreamAnnouncer();
  /** Typed structured preview (`structured_incremental`): title + closed blocks. */
  const [streamTitle, setStreamTitle] = useState<string | null>(null);
  const [streamBlocks, setStreamBlocks] = useState<Array<{ index: number; block: ContentBlock }>>(
    []
  );
  /** Attachment filenames for the in-flight turn — cite chips before ``result``. */
  const [streamSourceRefs, setStreamSourceRefs] = useState<string[]>([]);
  /** Preserves bubble height across preview → BlockRenderer to avoid layout jump. */
  const [streamBubbleMinHeight, setStreamBubbleMinHeight] = useState<number | undefined>();
  const messageEndRef = useRef<HTMLDivElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const dialogueNavEntries = useMemo(() => buildDialogueNavEntries(messages), [messages]);
  const showDialogueNav = shouldShowDialogueNav(dialogueNavEntries);
  /** Kimi only floats «scroll to latest» while the reader is above the end. */
  const [isAtThreadEnd, setIsAtThreadEnd] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamPreviewRafRef = useRef(0);
  const streamPreviewPendingRef = useRef('');
  const streamBubbleRef = useRef<HTMLDivElement | null>(null);
  const streamingAssistantIdRef = useRef<string | null>(null);

  /* The «scroll to latest» control is a stateful affordance, not permanent chrome:
     it only floats above the composer while the transcript is scrolled up. */
  useEffect(() => {
    const sentinel = messageEndRef.current;
    if (!sentinel || typeof IntersectionObserver === 'undefined') return;
    const root = sentinel.closest('.transcript');
    if (!root) return;
    const observer = new IntersectionObserver(
      entries => setIsAtThreadEnd(entries[0]?.isIntersecting ?? true),
      { root, threshold: 0 }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [threadId, messages.length, shellView]);

  /* Kimi subpages that hand work to the composer (Scheduled / product landing). */
  const composeFromPage = useCallback(
    (prompt: string) => {
      navigateShell('chat');
      setInput(prompt);
      requestAnimationFrame(() => composerInputRef.current?.focus());
    },
    [navigateShell]
  );

  /** Same-origin link to this contour — shared by the Invite and Get-app dialogs. */
  const shareLink = useMemo(
    () =>
      typeof window === 'undefined' ? '' : `${window.location.origin}${window.location.pathname}`,
    []
  );

  const copyShareLink = useCallback(
    async (successMessage: string) => {
      const link = shareLink || `${window.location.origin}${window.location.pathname}`;
      try {
        await navigator.clipboard.writeText(link);
        toast.success(successMessage);
      } catch {
        // Clipboard permission denied (non-secure origin) — surface the link itself
        // instead of pretending the copy worked.
        toast.error(link);
      }
    },
    [shareLink]
  );

  const scheduleStreamPreview = useCallback((text: string) => {
    streamPreviewPendingRef.current = text;
    if (streamPreviewRafRef.current !== 0) return;
    streamPreviewRafRef.current = requestAnimationFrame(() => {
      streamPreviewRafRef.current = 0;
      setStreamPreview(streamPreviewPendingRef.current);
    });
  }, []);

  /** Drop GFM draft only — keep typed title/blocks (handover to BlockRenderer). */
  const clearMarkdownStreamPreview = useCallback(() => {
    if (streamPreviewRafRef.current !== 0) {
      cancelAnimationFrame(streamPreviewRafRef.current);
      streamPreviewRafRef.current = 0;
    }
    streamPreviewPendingRef.current = '';
    setStreamPreview('');
  }, []);

  const clearStreamPreview = useCallback(() => {
    clearMarkdownStreamPreview();
    setStreamTitle(null);
    setStreamBlocks([]);
    setStreamSourceRefs([]);
  }, [clearMarkdownStreamPreview]);

  /**
   * Upsert typed frame by index: open paragraphs grow in place; a closed block
   * replaces the provisional one (streamObject superset — no remount flicker).
   */
  const appendStreamBlock = useCallback((index: number, block: ContentBlock) => {
    setStreamBlocks(prev => {
      const at = prev.findIndex(item => item.index === index);
      if (at >= 0) {
        const next = prev.slice();
        next[at] = { index, block };
        return next;
      }
      return [...prev, { index, block }].sort((a, b) => a.index - b.index);
    });
  }, []);

  /**
   * Typed preview document: the same shape `BlockRenderer` receives when the turn
   * finishes, so the handover only adds blocks instead of re-rendering them.
   * Null until the first block closes: the document title alone is not readable
   * content (it is hidden by the renderer), so it must not replace the typing
   * indicator with an empty bubble.
   * `meta`/`actions` are placeholders — the preview renders content, not HITL.
   */
  const streamDocument = useMemo<ContentDocument | null>(() => {
    if (streamBlocks.length === 0) return null;
    return {
      schema_version: 1,
      locale: getI18nLocale(),
      title: streamTitle,
      blocks: streamBlocks.map(item => item.block),
      actions: [],
      meta: {
        confidence: 1,
        requires_review: false,
        source_refs: streamSourceRefs,
      },
    };
  }, [streamBlocks, streamTitle, streamSourceRefs]);

  const lockStreamBubbleHeight = useCallback(() => {
    const el = streamBubbleRef.current;
    if (el) setStreamBubbleMinHeight(el.offsetHeight);
  }, []);

  const clearStreamBubbleHeight = useCallback(() => {
    setStreamBubbleMinHeight(undefined);
  }, []);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      if (streamPreviewRafRef.current !== 0) {
        cancelAnimationFrame(streamPreviewRafRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!artifactMessageId && !filesRail) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setArtifactMessageId(null);
      setFilesRail(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [artifactMessageId, filesRail]);

  const uploading = attachments.some(
    chip => chip.status === 'uploading' || chip.status === 'scanning'
  );

  // ── Лимит символов ───────────────────────────────────────────────────────
  const inputLength = input.length;
  const inputRemaining = INTENT_TEXT_LIMIT - inputLength;
  const overLimit = inputRemaining < 0;
  const nearLimit = !overLimit && inputRemaining <= COUNTER_WARN_THRESHOLD;

  const canSend = useMemo(() => {
    const hasText = input.trim().length > 0;
    const hasReadyAttachment = attachments.some(
      chip => chip.status === 'ready' && Boolean(chip.serverId)
    );
    // Send stays blocked while any chip is still uploading or scanning (W1 G04 / W2).
    return (hasText || hasReadyAttachment) && !busy && !uploading && !overLimit;
  }, [input, attachments, busy, uploading, overLimit]);

  const enqueueFiles = useCallback(
    (files: File[], meta: { sourceText?: string; origin?: 'paste' | 'file' } = {}) => {
      if (files.length === 0) return;
      const slots = MAX_ATTACHMENTS_PER_TURN - attachments.length;
      if (slots <= 0) {
        toast.error(t('toast.tooManyFiles', { count: MAX_ATTACHMENTS_PER_TURN }));
        return;
      }
      if (files.length > slots) {
        toast.error(t('toast.tooManyFiles', { count: MAX_ATTACHMENTS_PER_TURN }));
      }

      for (const file of files.slice(0, slots)) {
        const refusal = attachmentRefusalReason(file);
        if (refusal) {
          toast.error(`${file.name}: ${refusal}`);
          continue;
        }

        const localId = crypto.randomUUID();
        const previewUrl =
          attachmentFileKind(file.name) === 'image' ? URL.createObjectURL(file) : undefined;
        setAttachments(prev => [
          ...prev,
          {
            localId,
            filename: file.name,
            sizeBytes: file.size,
            status: 'uploading',
            sourceText: meta.sourceText,
            origin: meta.origin ?? 'file',
            previewUrl,
          },
        ]);

        void (async () => {
          try {
            const stored = await uploadAttachment(
              file,
              {
                threadId,
                userId,
                orgId,
                projectId: projectId.trim() || undefined,
              },
              phase => {
                if (phase === 'scanning') {
                  setAttachments(prev =>
                    prev.map(chip =>
                      chip.localId === localId
                        ? { ...chip, status: 'scanning', error: undefined }
                        : chip
                    )
                  );
                }
              }
            );
            // A refused file still exists as a row: it is shown with its reason
            // instead of vanishing, so the user learns *why* it never reached a turn.
            const failure = refusalLabel(stored);
            setAttachments(prev =>
              prev.map(chip =>
                chip.localId === localId
                  ? {
                      ...chip,
                      serverId: stored.attachment_id,
                      status: failure ? 'failed' : 'ready',
                      error: failure ?? undefined,
                      pageCount: stored.page_count,
                      mode: stored.mode,
                      rejectionReason: stored.rejection_reason,
                      serverStatus: stored.status,
                      containsPii: Boolean(stored.contains_pii),
                    }
                  : chip
              )
            );
            if (failure) toast.error(`${stored.filename}: ${failure}`);
          } catch (err) {
            const message = err instanceof Error ? err.message : t('toast.uploadFailed');
            setAttachments(prev =>
              prev.map(chip =>
                chip.localId === localId ? { ...chip, status: 'failed', error: message } : chip
              )
            );
            toast.error(`${file.name}: ${message.slice(0, 160)}`);
          }
        })();
      }
    },
    [attachments.length, threadId, userId, orgId, projectId]
  );

  const addFiles = useCallback(
    (files: File[]) => {
      enqueueFiles(files, { origin: 'file' });
    },
    [enqueueFiles]
  );

  const attachPastedText = useCallback(
    (text: string) => {
      const slots = MAX_ATTACHMENTS_PER_TURN - attachments.length;
      if (slots <= 0) {
        toast.error(t('composer.pasteSlotFull'));
        return;
      }
      const file = createPastedTextFile(text);
      if (file === null) {
        toast.error(t('composer.pasteTooLarge', { size: MAX_ATTACHMENT_LABEL }));
        return;
      }
      enqueueFiles([file], { sourceText: text, origin: 'paste' });
      toast.success(t('composer.pasteConverted'));
    },
    [attachments.length, enqueueFiles]
  );

  const handleComposerPaste = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const pasted = event.clipboardData.getData('text');
      if (!pasted || !shouldAutoAttachText(pasted)) return;
      event.preventDefault();
      attachPastedText(pasted);
    },
    [attachPastedText]
  );

  const removeAttachment = useCallback(
    (localId: string) => {
      const chip = attachments.find(item => item.localId === localId);
      if (chip?.serverId) {
        // Best effort: rows carry a TTL and a sweep reclaims them, so a failed
        // delete must never block the composer (060).
        void deleteAttachment(chip.serverId, userId, orgId).catch(() => {
          toast.error(t('toast.deleteFailed'));
        });
      }
      if (chip) revokeAttachmentPreview(chip);
      setAttachments(prev => prev.filter(item => item.localId !== localId));
    },
    [attachments, userId, orgId]
  );

  /** kimi.ai FileCard / shelf / citation page → right-rail preview pane. */
  const openAttachmentPreview = useCallback(
    (attachmentId: string, filename: string, page?: number) => {
      setArtifactMessageId(null);
      setFilesRail({
        mode: 'preview',
        id: attachmentId,
        filename,
        ...(typeof page === 'number' && page >= 1 ? { page } : {}),
      });
    },
    []
  );

  /** Paperclip click → «Файлы в чате» list rail. */
  const openAttachmentsList = useCallback(() => {
    setArtifactMessageId(null);
    setFilesRail({ mode: 'list' });
  }, []);

  const threadAttachments = useMemo(() => {
    const out: { id: string; filename: string; meta: string }[] = [];
    const seen = new Set<string>();
    for (const message of messages) {
      if (message.role !== 'user') continue;
      const ids = message.attachmentIds ?? [];
      const names = message.attachmentNames ?? [];
      for (let index = 0; index < names.length; index += 1) {
        const id = ids[index];
        const name = names[index];
        if (!id || !name || seen.has(id)) continue;
        seen.add(id);
        const ext = name.includes('.') ? (name.split('.').pop()?.toUpperCase() ?? '') : '';
        out.push({ id, filename: name, meta: ext });
      }
    }
    for (const chip of attachments) {
      if (!chip.serverId || seen.has(chip.serverId)) continue;
      seen.add(chip.serverId);
      out.push({
        id: chip.serverId,
        filename: chip.filename,
        meta: attachmentChipMeta(chip.filename, chip.sizeBytes),
      });
    }
    return out;
  }, [messages, attachments]);

  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;
  useEffect(() => {
    return () => {
      revokeAttachmentPreviews(attachmentsRef.current);
    };
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setDevMode(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let stopPing: (() => void) | null = null;

    void (async () => {
      try {
        const token = await ensureAccessToken(userId, orgId);
        if (cancelled) return;
        socket = connectSessionSocket(threadId, token, {
          onSubscribed: () => setWsConnected(true),
          onError: () => setWsConnected(false),
        });
        stopPing = startSessionSocketPing(socket);
      } catch {
        setWsConnected(false);
      }
    })();

    return () => {
      cancelled = true;
      stopPing?.();
      socket?.close();
      setWsConnected(false);
    };
  }, [threadId, userId, orgId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const turns = await fetchDialogTurns(threadId, 50, userId, orgId);
        if (cancelled || turns.length === 0) {
          return;
        }
        const restored: ChatMessage[] = [];
        for (const turn of turns) {
          if (turn.role === 'user') {
            const payload =
              turn.payload && typeof turn.payload === 'object' && !Array.isArray(turn.payload)
                ? (turn.payload as Record<string, unknown>)
                : null;
            const hydrated = await hydrateUserTurn(turn.content, payload, userId, orgId);
            // Empty text after stripping a corrupt HITL resume — still keep the
            // turn when files are present; otherwise skip the machine shell.
            if (!hydrated.text && hydrated.attachmentNames.length === 0) {
              continue;
            }
            restored.push({
              id: turn.id ?? crypto.randomUUID(),
              role: 'user',
              text: hydrated.text,
              attachmentIds: hydrated.attachmentIds,
              attachmentNames: hydrated.attachmentNames,
            });
            continue;
          }
          const { document, requiresReview, hitlCards, revision } = parseAssistantPayload(
            turn.payload,
            turn.content
          );
          const hydratedCards = await hydratePendingHitlCards(hitlCards, userId, orgId);
          const feedback = (turn.payload as { feedback?: { like?: boolean; dislike?: boolean } })
            ?.feedback;
          restored.push({
            id: turn.id ?? crypto.randomUUID(),
            role: 'assistant',
            document,
            revision,
            hitlCards: hydratedCards,
            _requiresReview: requiresReview,
            _pendingReview: false,
            _feedbackLike: feedback?.like || false,
            _feedbackDislike: feedback?.dislike || false,
            status: 'success',
            error: undefined,
          });
        }
        if (!cancelled) {
          setMessages(restored);
          // Pane is opt-in (user click) — never auto-restore open state (Kimi chat parity).
          setArtifactMessageId(null);
          setFilesRail(null);
          void refreshSessionShelf();
        }
      } catch (err) {
        console.warn('Session hydrate failed:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId, refreshSessionShelf, threadId, userId]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const handleHitlResolved = useCallback((messageId: string, event: HitlResolvedEvent) => {
    const { card, resumed, revision } = event;
    setMessages(prev =>
      prev.map(msg => {
        if (msg.id !== messageId || msg.role !== 'assistant') return msg;
        const hitlCards = (msg.hitlCards ?? [])
          .map(existing => (existing.card_id === card.card_id ? card : existing))
          .filter(existing => existing.status === 'pending');
        return resumed?.output
          ? {
              ...msg,
              document: resumed.output,
              // The resume envelope carries the diff for the answer that replaced this
              // one; without it (a plain choice resume) no marks apply.
              revision: revision ?? null,
              hitlCards,
              _pendingReview: false,
              _requiresReview: resumed.requires_review,
              status: resumed.status,
              error: resumed.error ?? undefined,
            }
          : {
              ...msg,
              hitlCards,
              _pendingReview: hitlCards.length > 0 ? false : msg._pendingReview,
            };
      })
    );
    if (resumed?.output) {
      toast.success(t('toast.resuming'));
    }
  }, []);

  const handleMemoryCardCreated = useCallback(
    (card: HITLCardView, label: string) => {
      void (async () => {
        const hydrated = await hydratePendingHitlCards([card], userId, orgId);
        setMessages(prev => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            document: textAsDocument(label),
            hitlCards: hydrated,
            _requiresReview: true,
            _pendingReview: false,
            status: 'partial',
          },
        ]);
      })();
    },
    [userId, orgId]
  );

  async function send() {
    const typed = input.trim();
    const outgoing = attachments.filter(chip => chip.status === 'ready' && chip.serverId);
    const attachmentIds = outgoing.map(chip => chip.serverId as string);
    const attachmentNames = outgoing.map(chip => chip.filename);
    // Attachment-only send: intent text cannot be empty (API), so use a short default.
    const text = typed || (attachmentIds.length > 0 ? t('composer.pastedDefaultPrompt') : '');
    if (!text || busy || uploading) return;

    // Дублируем клиентскую валидацию из `processIntent` — здесь она защищает
    // от случайного сабмита по Enter при вставке слишком длинного текста.
    if (text.length > INTENT_TEXT_LIMIT) {
      toast.error(
        t('error.messageTooLong', {
          used: formatNumber(text.length),
          limit: formatNumber(INTENT_TEXT_LIMIT),
        })
      );
      return;
    }

    // TTFVF: старт — синхронно, до первого `await`. Иначе в метрику попадёт
    // ожидание токена/сети, и «первый видимый кадр» перестанет быть клиентским
    // показателем (серверное время меряет `palatium_sse_first_block_seconds`).
    const turnStartedAt = markFirstVisualStart();

    setInput('');
    setBusy(true);
    clearStreamPreview();
    setStreamSourceRefs(attachmentNames);
    a11y.reset();
    setPendingNode(null);
    clearStreamBubbleHeight();
    streamAbortRef.current?.abort();
    const abort = new AbortController();
    streamAbortRef.current = abort;
    const userMsgId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    streamingAssistantIdRef.current = assistantId;
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', text, attachmentIds, attachmentNames },
      {
        id: assistantId,
        role: 'assistant',
        document: null,
        hitlCards: [],
        _streaming: true,
      },
    ]);
    // Замер ставится после commit'а состояния: кадр, который ждёт `measureFirstVisual`,
    // — первый кадр с орбом и сообщением пользователя, а не предыдущий.
    void measureFirstVisual(turnStartedAt);

    try {
      let hasTextDelta = false;
      let hasTypedPreview = false;
      let liveRevision: DocumentRevision | null = null;
      const result = await processIntentStream(text, threadId, userId, orgId, attachmentIds, {
        signal: abort.signal,
        composerMode: effectiveComposerMode,
        useMemory: readSettingsPrefs().learnFromChats,
        onDocumentTitle: title => {
          hasTypedPreview = true;
          setStreamTitle(title);
          a11y.announceTitle(title);
        },
        onBlockDelta: (index, block) => {
          hasTypedPreview = true;
          // Typed surface wins: never leave StreamMarkdownPreview under BlockRenderer.
          clearMarkdownStreamPreview();
          appendStreamBlock(index, block);
          a11y.announceBlock(index, block);
        },
        onTextDelta: (_delta, accumulated) => {
          hasTextDelta = true;
          if (hasTypedPreview) return;
          scheduleStreamPreview(accumulated);
          a11y.announceMarkdown(accumulated);
        },
        onAnswerDelta: (_delta, accumulated) => {
          if (hasTypedPreview || hasTextDelta) return;
          scheduleStreamPreview(accumulated);
          a11y.announceMarkdown(accumulated);
        },
        // Diff приходит последним кадром: до него документ ещё не финальный.
        onRevision: revision => {
          liveRevision = revision;
        },
        // Единственный сигнал «что сейчас делает граф» — узел LangGraph.
        onHop: node => setPendingNode(node),
      });
      const hydratedCards = await hydratePendingHitlCards(
        fieldsFromFormatterResult(result).hitlCards,
        userId,
        orgId
      );
      lockStreamBubbleHeight();
      const assistant: AssistantChatMessage = {
        ...buildAssistantMessage({ ...result, hitl_cards: hydratedCards }, assistantId),
        revision: liveRevision,
      };
      // Document first, then drop preview in the same turn so UI never flashes empty.
      setMessages(prev =>
        prev.map(msg => (msg.id === assistantId && msg.role === 'assistant' ? assistant : msg))
      );
      clearStreamPreview();
      // Один агрегированный финал вместо лавины: «ответ готов» (+ предупреждение
      // о проверке, если оно есть), заголовок — только если кадром не пришёл.
      a11y.announceReady(result);
      streamingAssistantIdRef.current = null;
      // Industry chat pattern (ChatGPT/Claude/Gemini): composer is staging only.
      // After a successful send the file lives on the user message; ready chips
      // leave the composer. Failed chips stay so the user can see why / retry.
      setAttachments(prev => {
        for (const chip of prev) {
          if (chip.status === 'ready') revokeAttachmentPreview(chip);
        }
        return prev.filter(chip => chip.status !== 'ready');
      });
      requestAnimationFrame(() => clearStreamBubbleHeight());
      void refreshSessionShelf();
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setMessages(prev => prev.filter(msg => msg.id !== assistantId));
        clearStreamPreview();
        return;
      }
      // Сообщение уже humanized в `errorDetail` (см. client.ts).
      const message = err instanceof Error ? err.message : t('error.requestFailed');
      setMessages(prev =>
        prev.map(msg =>
          msg.id === assistantId && msg.role === 'assistant'
            ? {
                id: assistantId,
                role: 'assistant',
                document: null,
                hitlCards: [],
                _requiresReview: false,
                _pendingReview: false,
                error: message,
                status: 'failure',
              }
            : msg
        )
      );
      clearStreamPreview();
      // Ошибка — тоже часть ответа: без объявления пользователь скринридера
      // остаётся с предыдущим «ответ готов» и не знает, что стрим упал.
      a11y.announceFailure(message);
      // Keep ready chips on failure so the user can retry without re-upload.
    } finally {
      if (streamAbortRef.current === abort) {
        streamAbortRef.current = null;
      }
      streamingAssistantIdRef.current = null;
      setBusy(false);
    }
  }

  const regenerateResponse = useCallback(
    async (messageId: string) => {
      if (busy) return;
      const { kept, userMessage } = messagesKeptForRegenerate(messages, messageId);
      if (!userMessage || userMessage.role !== 'user') return;

      const keep = keepCountBeforeRegenerate(messages, messageId);
      try {
        if (threadId) {
          await truncateDialogTurns(threadId, keep, userId, orgId);
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : t('toast.regenerateFailed'));
        return;
      }

      const placeholderId = messageId;
      const turnStartedAt = markFirstVisualStart();
      const regeneratingPlaceholder: AssistantChatMessage = {
        id: placeholderId,
        role: 'assistant',
        document: null,
        _regenerating: true,
        status: 'partial',
      };
      setMessages([...kept, regeneratingPlaceholder]);
      setArtifactMessageId(null);
      setBusy(true);
      clearStreamPreview();
      setStreamSourceRefs(userMessage.attachmentNames ?? []);
      a11y.reset();
      setPendingNode(null);
      clearStreamBubbleHeight();
      streamingAssistantIdRef.current = placeholderId;
      streamAbortRef.current?.abort();
      const abort = new AbortController();
      streamAbortRef.current = abort;
      void measureFirstVisual(turnStartedAt);
      try {
        let hasTextDelta = false;
        let hasTypedPreview = false;
        const result = await processIntentStream(
          userMessage.text,
          threadId,
          userId,
          orgId,
          userMessage.attachmentIds ?? [],
          {
            signal: abort.signal,
            composerMode: effectiveComposerMode,
            useMemory: readSettingsPrefs().learnFromChats,
            onDocumentTitle: title => {
              hasTypedPreview = true;
              setStreamTitle(title);
              a11y.announceTitle(title);
            },
            onBlockDelta: (index, block) => {
              hasTypedPreview = true;
              clearMarkdownStreamPreview();
              appendStreamBlock(index, block);
              a11y.announceBlock(index, block);
            },
            onTextDelta: (_delta, accumulated) => {
              hasTextDelta = true;
              if (hasTypedPreview) return;
              scheduleStreamPreview(accumulated);
              a11y.announceMarkdown(accumulated);
            },
            onAnswerDelta: (_delta, accumulated) => {
              if (hasTypedPreview || hasTextDelta) return;
              scheduleStreamPreview(accumulated);
              a11y.announceMarkdown(accumulated);
            },
            onHop: node => setPendingNode(node),
          }
        );
        const hydratedCards = await hydratePendingHitlCards(
          fieldsFromFormatterResult(result).hitlCards,
          userId,
          orgId
        );
        lockStreamBubbleHeight();
        const assistant = buildAssistantMessage(
          { ...result, hitl_cards: hydratedCards },
          placeholderId
        );
        setMessages(prev =>
          prev.map(msg => (msg.id === placeholderId && msg.role === 'assistant' ? assistant : msg))
        );
        clearStreamPreview();
        a11y.announceReady(result);
        streamingAssistantIdRef.current = null;
        requestAnimationFrame(() => clearStreamBubbleHeight());
        toast.success(t('toast.regenerated'));
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          setMessages(prev =>
            prev.map(msg =>
              msg.id === placeholderId && msg.role === 'assistant'
                ? { ...msg, _regenerating: false }
                : msg
            )
          );
          clearStreamPreview();
          return;
        }
        setMessages(prev =>
          prev.map(msg =>
            msg.id === placeholderId && msg.role === 'assistant'
              ? {
                  ...msg,
                  error: err instanceof Error ? err.message : t('toast.regenerateFailed'),
                  _regenerating: false,
                }
              : msg
          )
        );
        clearStreamPreview();
        a11y.announceFailure(err instanceof Error ? err.message : t('toast.regenerateFailed'));
        toast.error(t('toast.regenerateFailed'));
      } finally {
        if (streamAbortRef.current === abort) {
          streamAbortRef.current = null;
        }
        streamingAssistantIdRef.current = null;
        setBusy(false);
      }
    },
    [
      busy,
      messages,
      threadId,
      userId,
      orgId,
      effectiveComposerMode,
      clearStreamPreview,
      clearMarkdownStreamPreview,
      appendStreamBlock,
      scheduleStreamPreview,
      lockStreamBubbleHeight,
      clearStreamBubbleHeight,
      a11y,
    ]
  );

  const handleFeedback = useCallback(
    async (messageId: string, type: 'like' | 'dislike') => {
      const message = messages.find(m => m.id === messageId);
      if (!message || message.role !== 'assistant') return;
      if (message._feedbackSending) return;

      const isLike = type === 'like';
      const isCurrentlyActive = isLike ? message._feedbackLike : message._feedbackDislike;
      const newActive = !isCurrentlyActive;

      setMessages(prev =>
        prev.map(msg => {
          if (msg.id !== messageId || msg.role !== 'assistant') return msg;
          return {
            ...msg,
            _feedbackLike: isLike ? newActive : false,
            _feedbackDislike: isLike ? false : newActive,
            _feedbackSending: true,
          };
        })
      );

      try {
        await sendFeedback(messageId, newActive ? type : 'clear', userId, orgId, threadId);
        setMessages(prev =>
          prev.map(msg => {
            if (msg.id !== messageId || msg.role !== 'assistant') return msg;
            return { ...msg, _feedbackSending: false };
          })
        );
      } catch (err) {
        console.warn('Feedback not saved on server:', err);
        setMessages(prev =>
          prev.map(msg => {
            if (msg.id !== messageId || msg.role !== 'assistant') return msg;
            return { ...msg, _feedbackSending: false };
          })
        );
        toast.error(t('toast.feedbackFailed'));
      }
    },
    [messages, userId, orgId, threadId]
  );

  const copyMessageContent = useCallback((message: ChatMessage) => {
    if (message.role !== 'assistant' || !message.document) return;
    const text = getDocumentPlainText(message.document);
    if (!text) return;
    void navigator.clipboard.writeText(text).then(
      () => toast.success(t('action.copied')),
      () => undefined
    );
  }, []);

  const shareMessageContent = useCallback(async (message: ChatMessage) => {
    if (message.role !== 'assistant' || !message.document) return;
    const text = getDocumentPlainText(message.document);
    if (!text) return;
    const title = message.document.title?.trim() || t('action.share');
    const result = await shareAnswerText({ title, text });
    if (result === 'copied') toast.success(t('action.shareCopied'));
    else if (result === 'failed') toast.error(t('action.shareFailed'));
  }, []);

  const copyUserMessage = useCallback((message: ChatMessage) => {
    if (message.role !== 'user') return;
    const text = message.text.trim();
    if (!text) return;
    void navigator.clipboard.writeText(text).then(
      () => toast.success(t('action.copied')),
      () => undefined
    );
  }, []);

  /** Load user turn into composer for rewrite + resend (kimi Edit). */
  const editUserMessage = useCallback(
    (message: ChatMessage) => {
      if (message.role !== 'user' || busy) return;
      const messageId = message.id;
      const keep = keepCountBeforeEdit(messages, messageId);
      const nextMessages = messagesKeptBeforeEdit(messages, messageId);
      const text = message.text;

      void (async () => {
        try {
          if (threadId) {
            await truncateDialogTurns(threadId, keep, userId, orgId);
          }
        } catch (error) {
          toast.error(error instanceof Error ? error.message : t('toast.editFailed'));
          return;
        }
        setMessages(nextMessages);
        setArtifactMessageId(null);
        setAttachments([]);
        setInput(text);
        requestAnimationFrame(() => composerInputRef.current?.focus());
        toast.success(t('toast.messageReadyToEdit'));
      })();
    },
    [busy, messages, threadId, userId, orgId]
  );

  // Никакого `window.location.reload()`: виджет встроен в страницу СЭД и не имеет
  // права её перезагружать. Новый тред = сброс состояния в памяти + новый threadId.
  const deriveThreadTitle = useCallback((items: ChatMessage[]) => {
    const firstUser = items.find(m => m.role === 'user');
    if (firstUser && firstUser.role === 'user') {
      const text = firstUser.text.trim();
      return text.length > 48 ? `${text.slice(0, 48)}…` : text || t('sidebar.untitled');
    }
    return t('sidebar.emptyTitle');
  }, []);

  const openRenameThread = useCallback(
    (targetId: string) => {
      const title =
        sessionShelf.find(row => row.id === targetId)?.title ??
        (targetId === threadId ? deriveThreadTitle(messages) : t('sidebar.untitled'));
      setRenameTarget({ id: targetId, title });
      setRenameDraft(title);
    },
    [deriveThreadTitle, messages, sessionShelf, threadId]
  );

  const submitRenameThread = useCallback(async () => {
    if (!renameTarget || renameBusy) return;
    const next = renameDraft.trim();
    if (!next) {
      toast.error(t('sidebar.renameEmpty'));
      return;
    }
    setRenameBusy(true);
    try {
      await renameSession(renameTarget.id, next, userId, orgId);
      const renamedId = renameTarget.id;
      setSessionShelf(prev => {
        const now = new Date().toISOString();
        const updated = prev.map(row =>
          row.id === renamedId ? { ...row, title: next, updatedAt: now } : row
        );
        // Persist rename even if the live thread was not yet on the shelf.
        if (updated.some(row => row.id === renamedId)) return updated;
        return [
          { id: renamedId, title: next, projectId: projectId.trim() || null, updatedAt: now },
          ...updated,
        ];
      });
      setRenameTarget(null);
      toast.success(t('sidebar.renameDone'));
    } catch (err) {
      console.warn('Rename session failed:', err);
      toast.error(t('error.requestFailed'));
    } finally {
      setRenameBusy(false);
    }
  }, [orgId, projectId, renameBusy, renameDraft, renameTarget, userId]);

  const submitArchiveThread = useCallback(async () => {
    if (!archiveTarget || archiveBusy) return;
    setArchiveBusy(true);
    try {
      await archiveSession(archiveTarget.id, userId, orgId);
      setSessionShelf(prev => prev.filter(row => row.id !== archiveTarget.id));
      if (archiveTarget.id === threadId) {
        handleNewThreadRef.current?.();
      }
      setArchiveTarget(null);
      toast.success(t('sidebar.deleteDone'));
    } catch (err) {
      console.warn('Archive session failed:', err);
      toast.error(t('error.requestFailed'));
    } finally {
      setArchiveBusy(false);
    }
  }, [archiveBusy, archiveTarget, orgId, threadId, userId]);

  const submitBulkArchive = useCallback(async () => {
    if (!bulkArchive || bulkArchive.length === 0 || archiveBusy) return;
    setArchiveBusy(true);
    const ids = bulkArchive.map(item => item.id);
    try {
      for (const id of ids) {
        await archiveSession(id, userId, orgId);
      }
      setSessionShelf(prev => prev.filter(row => !ids.includes(row.id)));
      if (ids.includes(threadId)) {
        handleNewThreadRef.current?.();
      }
      setBulkArchive(null);
      toast.success(t('historyPage.bulkDeleteDone'));
    } catch (err) {
      console.warn('Bulk archive failed:', err);
      toast.error(t('error.requestFailed'));
    } finally {
      setArchiveBusy(false);
    }
  }, [archiveBusy, bulkArchive, orgId, threadId, userId]);

  const openRenameProject = useCallback(
    (id: string) => {
      const title = projects.find(p => p.id === id)?.title ?? t('sidebar.untitled');
      setProjectRename({ id, title });
      setProjectRenameDraft(title);
    },
    [projects]
  );

  const submitRenameProject = useCallback(async () => {
    if (!projectRename || projectRenameBusy) return;
    const next = projectRenameDraft.trim();
    if (!next) {
      toast.error(t('sidebar.renameEmpty'));
      return;
    }
    setProjectRenameBusy(true);
    try {
      try {
        const updated = await renameProject(projectRename.id, next, userId, orgId);
        setProjects(prev =>
          prev.map(p => (p.id === updated.id ? { ...p, title: updated.title } : p))
        );
      } catch {
        /* Standalone without API — rename in memory. */
        setProjects(prev => prev.map(p => (p.id === projectRename.id ? { ...p, title: next } : p)));
      }
      setProjectRename(null);
      toast.success(t('sidebar.renameDone'));
    } finally {
      setProjectRenameBusy(false);
    }
  }, [orgId, projectRename, projectRenameBusy, projectRenameDraft, userId]);

  const pinProjectTop = useCallback((id: string) => {
    setProjects(prev => {
      const hit = prev.find(p => p.id === id);
      if (!hit) return prev;
      return [hit, ...prev.filter(p => p.id !== id)];
    });
  }, []);

  const submitDeleteProject = useCallback(async () => {
    if (!projectDelete || projectDeleteBusy) return;
    setProjectDeleteBusy(true);
    try {
      try {
        await deleteProject(projectDelete.id, userId, orgId);
      } catch (err) {
        console.warn('Delete project API failed; dropping local row:', err);
      }
      setProjects(prev => prev.filter(p => p.id !== projectDelete.id));
      if (projectId === projectDelete.id) {
        setProjectId('');
        navigateShell('chat');
      }
      setProjectDelete(null);
      toast.success(t('sidebar.deleteDone'));
    } finally {
      setProjectDeleteBusy(false);
    }
  }, [navigateShell, orgId, projectDelete, projectDeleteBusy, projectId, userId]);

  const handleNewThread = useCallback(() => {
    void refreshSessionShelf();
    startNewThreadInRuntime();
    setMessages([]);
    setAttachments(prev => {
      revokeAttachmentPreviews(prev);
      return [];
    });
    setArtifactMessageId(null);
    setFilesRail(null);
    a11y.reset();
    navigateShell('chat');
    collapseNavIfNarrow();
  }, [a11y, collapseNavIfNarrow, navigateShell, refreshSessionShelf]);

  handleNewThreadRef.current = handleNewThread;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        handleNewThreadRef.current?.();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setSidebarCollapsed(v => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  /* Narrow shell: Escape dismisses the off-canvas drawer, matching the scrim. */
  useEffect(() => {
    if (!isNarrowShell || sidebarCollapsed) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSidebarCollapsed(true);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isNarrowShell, sidebarCollapsed]);

  const handleSelectThread = useCallback(
    (id: string) => {
      if (id === threadId) {
        collapseNavIfNarrow();
        return;
      }
      switchThreadInRuntime(id);
      setMessages([]);
      setAttachments(prev => {
        revokeAttachmentPreviews(prev);
        return [];
      });
      setArtifactMessageId(null);
      setFilesRail(null);
      a11y.reset();
      collapseNavIfNarrow();
    },
    [a11y, collapseNavIfNarrow, threadId]
  );

  const historyThreads: HistoryThreadItem[] = useMemo(() => {
    const liveTitle = messages.length > 0 ? deriveThreadTitle(messages) : t('sidebar.emptyTitle');
    /**
     * Only surface the live thread once it has content or the server already
     * knows it — kimi.ai never lists the blank "New chat" you are typing into.
     * Renamed shelf titles must not be overwritten by first-message derivation.
     */
    const known = sessionShelf.some(row => row.id === threadId);
    const merged =
      !known && messages.length === 0
        ? sessionShelf
        : mergeShelfWithLiveThread(sessionShelf, threadId, liveTitle, projectId.trim() || null, [
            t('sidebar.untitled'),
            t('sidebar.emptyTitle'),
          ]);
    const filterId = projectId.trim();
    if (!filterId) return merged;
    return merged.filter(row => row.projectId === filterId || row.id === threadId);
  }, [deriveThreadTitle, messages, projectId, sessionShelf, threadId]);

  /* Home publisher shortcuts — cut products omitted (3D / Build / Design / …). */
  const productChips: ProductChipItem[] = useMemo(
    () => [
      { id: 'slides', label: t('chip.slides'), icon: <KimiGlyph name="slides" size={18} /> },
      {
        id: 'deep',
        label: t('chip.deepResearch'),
        icon: <KimiGlyph name="deepResearch" size={18} />,
      },
      { id: 'docs', label: t('chip.docs'), icon: <KimiGlyph name="docs" size={18} /> },
      { id: 'sheets', label: t('chip.sheets'), icon: <KimiGlyph name="sheets" size={18} /> },
    ],
    []
  );

  // ── Counter class (для CSS) ──────────────────────────────────────────────
  const counterClass = overLimit
    ? 'composer-counter composer-counter--over'
    : nearLimit
      ? 'composer-counter composer-counter--warn'
      : 'composer-counter';

  // Screen readers announce only at warn/over thresholds, not on every keystroke.
  const counterLive: 'polite' | 'off' = overLimit || nearLimit ? 'polite' : 'off';

  const artifactMessage =
    artifactMessageId === null
      ? null
      : messages.find(
          (msg): msg is AssistantChatMessage =>
            msg.id === artifactMessageId && msg.role === 'assistant' && Boolean(msg.document)
        );

  const topBadges = [
    ...(devMode ? [`🔧 ${t('badge.dev')}`] : []),
    ...(devMode && wsConnected ? [t('badge.ws')] : []),
    ...(devMode && hostStatus === 'standalone' ? [t('badge.standalone')] : []),
  ];

  const navDrawerOpen = isNarrowShell && !sidebarCollapsed;

  const setSideConsoleWidth = useCallback((pct: number) => {
    const workspaceW = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    const next = clampSideConsoleWidthPct(pct, workspaceW);
    setSideConsoleWidthPct(next);
    writeSideConsoleWidthPct(next);
  }, []);

  const resetSideConsoleWidth = useCallback(() => {
    const workspaceW = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    const next = clampSideConsoleWidthPct(SIDE_CONSOLE_WIDTH_DEFAULT, workspaceW);
    setSideConsoleWidthPct(next);
    writeSideConsoleWidthPct(next);
  }, []);

  /*
   * Keep ``--side-console-width`` inside chat-min + pane-min whenever the
   * dual-pane opens or the workspace resizes — raw 70% overflows ~1280 stages.
   */
  useEffect(() => {
    if (!canResizeSideConsole) return;
    const node = workspaceRef.current;
    if (!node) return;

    const apply = () => {
      const workspaceW = node.getBoundingClientRect().width;
      setSideConsoleWidthPct(prev => {
        const next = clampSideConsoleWidthPct(prev, workspaceW);
        if (next !== prev) writeSideConsoleWidthPct(next);
        return next === prev ? prev : next;
      });
    };

    apply();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', apply);
      return () => window.removeEventListener('resize', apply);
    }
    const ro = new ResizeObserver(() => apply());
    ro.observe(node);
    return () => ro.disconnect();
  }, [canResizeSideConsole]);

  /* kimi.ai serves settings as a full page: the left rail becomes the settings
     nav, so the history sidebar and stage are replaced entirely. */
  if (shellView === 'settings') {
    return (
      <SettingsPage
        section={settingsSection}
        onSection={navigateSettings}
        onBack={() => navigateShell('chat')}
        userName={userName}
        threadId={threadId}
        userId={userId}
        orgId={orgId}
        onMemoryCardCreated={handleMemoryCardCreated}
      />
    );
  }

  return (
    <div
      ref={shellRef}
      className={`shell${artifactMessage || filesRail ? ' is-artifact-open' : ''}${
        filesRail?.mode === 'list' ? ' is-files-list' : ''
      }${filesRail?.mode === 'preview' ? ' is-files-preview' : ''}${
        artifactMessage && !filesRail ? ' is-artifact-doc' : ''
      }${navDrawerOpen ? ' is-nav-open' : ''}${isNarrowShell ? ' is-narrow' : ''}${
        isCompactShell ? ' is-compact' : ''
      }${canResizeSideConsole ? ' is-side-console-resizable' : ''}`}
      part="shell"
      data-density={isCompactShell ? 'compact' : 'comfortable'}
      style={
        canResizeSideConsole
          ? ({
              ['--side-console-width']: `${sideConsoleWidthPct}%`,
            } as CSSProperties)
          : undefined
      }
    >
      {/*
        Full Kimi frame (K3): ZONE_NAV history shelf + stage
        (ZONE_TOP / ZONE_BODY|HERO / ZONE_FOOTER). UI Upgrade.
        Organic texture — ::before on `.shell`.
        P5: narrow = glass off-canvas drawer (Brand Book UI Upgrade).
      */}
      {navDrawerOpen ? (
        <button
          type="button"
          className="nav-scrim"
          aria-label={t('sidebar.collapse')}
          onClick={() => setSidebarCollapsed(true)}
        />
      ) : null}
      <HistorySidebar
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(v => !v)}
        threads={historyThreads}
        projects={projects.map(p => ({ id: p.id, title: p.title }))}
        activeThreadId={threadId}
        activeView={shellView}
        onSelectThread={id => {
          const pinned = sessionShelf.find(row => row.id === id)?.projectId;
          if (pinned) setProjectId(pinned);
          handleSelectThread(id);
        }}
        onNewChat={handleNewThread}
        onNavigate={navigateShell}
        onPinThreadTop={handlePinThreadTop}
        pinnedThreadIds={pinnedThreadIds}
        onOpenSettings={() => navigateShell('settings')}
        userName={userName}
        offcanvas={isNarrowShell}
        offcanvasHidden={isNarrowShell && sidebarCollapsed}
        labels={{
          nav: t('sidebar.nav'),
          newChat: t('header.newChat'),
          newChatHint: t('header.newChatHint'),
          collapse: t('sidebar.collapse'),
          expand: t('sidebar.expand'),
          history: t('sidebar.history'),
          projects: t('sidebar.projects'),
          createProject: t('sidebar.createProject'),
          projectTitleHint: t('sidebar.projectTitleHint'),
          renameProject: t('project.action.rename'),
          pinProject: t('project.action.pin'),
          deleteProject: t('project.action.delete'),
          pin: t('sidebar.pin'),
          unpin: t('sidebar.unpin'),
          pinnedSection: t('sidebar.pinnedSection'),
          profile: t('sidebar.profile'),
          settings: t('sidebar.settings'),
          themeHint: t('sidebar.themeHint'),
          rename: t('sidebar.rename'),
          delete: t('sidebar.delete'),
          allChats: t('sidebar.allChats'),
        }}
        activeProjectId={projectId.trim() || null}
        onSelectProject={id => {
          if (id) navigateProject(id);
          else {
            setProjectId('');
            navigateShell('chat');
          }
        }}
        onRenameProject={openRenameProject}
        onPinProject={pinProjectTop}
        onDeleteProject={id => {
          const title = projects.find(p => p.id === id)?.title ?? t('sidebar.untitled');
          setProjectDelete({ id, title });
        }}
        onRenameThread={openRenameThread}
        onDeleteThread={id => {
          const title =
            sessionShelf.find(row => row.id === id)?.title ??
            (id === threadId ? deriveThreadTitle(messages) : t('sidebar.untitled'));
          setArchiveTarget({ id, title });
        }}
      />

      <div className="shell-stage">
        {/*
          Desktop collapsed rail: stage expand control (kimi `.sidebar-main-trigger`).
          Narrow: TopBar ``showNavToggle`` owns open/close — do not render both.
        */}
        {sidebarCollapsed && !isNarrowShell ? (
          <span className="sidebar-main-trigger">
            <button
              type="button"
              className="sidebar-main-trigger__button sidebar-main-trigger__button--expand"
              aria-label={t('sidebar.expand')}
              aria-keyshortcuts="Control+B"
              onClick={() => setSidebarCollapsed(false)}
            >
              <KimiGlyph name="toggle" size={20} />
            </button>
            <span className="history-sidebar__tip" role="tooltip">
              {t('sidebar.expand')}
              <span className="history-sidebar__tip-keys" aria-hidden>
                <kbd className="history-sidebar__tip-key">Ctrl</kbd>
                <kbd className="history-sidebar__tip-key">B</kbd>
              </span>
            </span>
          </span>
        ) : null}
        <TopBar
          title={t('app.title')}
          threadTitle={
            messages.length > 0
              ? (historyThreads.find(row => row.id === threadId)?.title ?? t('sidebar.emptyTitle'))
              : null
          }
          hasMessages={messages.length > 0}
          attachmentCount={threadAttachments.length}
          threadAttachments={threadAttachments}
          newChatLabel={t('header.newChat')}
          collapseLabel={t('header.collapse')}
          onNewChat={handleNewThread}
          onCollapse={mode === 'host' ? () => setPanelOpen(false) : undefined}
          showNavToggle={isNarrowShell}
          navToggleLabel={sidebarCollapsed ? t('sidebar.expand') : t('sidebar.collapse')}
          navToggleExpand={sidebarCollapsed}
          onToggleNav={() => setSidebarCollapsed(v => !v)}
          badges={topBadges}
          threadHint={devMode ? `${threadId.slice(0, 18)}…` : null}
          bare={FULL_PAGE_VIEWS.includes(shellView)}
          pageTitle={null}
          pageTitleIcon={null}
          pageTabs={
            shellView === 'plugins' || shellView === 'skills'
              ? [
                  { id: 'plugins', label: t('nav.plugins') },
                  { id: 'skills', label: t('nav.skills') },
                ]
              : []
          }
          activePageTab={shellView === 'skills' ? 'skills' : 'plugins'}
          onPageTabChange={id => navigateShell(id === 'skills' ? 'skills' : 'plugins')}
          onRenameThread={() => openRenameThread(threadId)}
          threadPinned={pinnedThreadIds.includes(threadId)}
          onPinThread={() => handlePinThreadTop(threadId)}
          onDeleteThread={() =>
            setArchiveTarget({
              id: threadId,
              title:
                historyThreads.find(row => row.id === threadId)?.title ??
                deriveThreadTitle(messages),
            })
          }
          onShareThread={() => void copyShareLink(t('invite.copied'))}
          onAddAttachments={() => fileInputRef.current?.click()}
          onOpenAttachmentsList={openAttachmentsList}
          onOpenAttachment={openAttachmentPreview}
        />

        {/*
          kimi.ai: workspace = chat column (messages+composer) | side-console.
          TopBar stays on the stage so home landing CSS keeps working.
        */}
        <div className="shell-workspace" ref={workspaceRef}>
          <div className="shell-chat-column">
            {/* [ZONE_BODY] — лента / marketplace */}
            <div className="shell-main" data-zone="ZONE_BODY">
              {shellView === 'plugins' || shellView === 'skills' ? (
                <Suspense fallback={<div className="market-page__loading" aria-busy="true" />}>
                  {shellView === 'plugins' ? (
                    <PluginsPage
                      activeTab="plugins"
                      onTabChange={tab => navigateShell(tab === 'skills' ? 'skills' : 'plugins')}
                    />
                  ) : (
                    <SkillsPage
                      activeTab="skills"
                      onTabChange={tab => navigateShell(tab === 'skills' ? 'skills' : 'plugins')}
                    />
                  )}
                </Suspense>
              ) : null}
              {shellView === 'scheduled' ? (
                <Suspense fallback={<div className="market-page__loading" aria-busy="true" />}>
                  <ScheduledTasksPage onCompose={composeFromPage} />
                </Suspense>
              ) : null}
              {shellView === 'history' ? (
                <Suspense fallback={<div className="market-page__loading" aria-busy="true" />}>
                  <ChatHistoryPage
                    threads={historyThreads.map(thread => {
                      if (thread.id !== threadId || messages.length === 0) return thread;
                      const assistant = [...messages]
                        .reverse()
                        .find(message => message.role === 'assistant' && message.document);
                      let snippetSource = '';
                      if (assistant && assistant.role === 'assistant' && assistant.document) {
                        snippetSource = [
                          assistant.document.title,
                          ...assistant.document.blocks
                            .filter(
                              (block): block is { type: 'paragraph'; text: string } =>
                                block.type === 'paragraph' && typeof block.text === 'string'
                            )
                            .map(block => block.text),
                        ]
                          .filter(Boolean)
                          .join(' ');
                      } else {
                        const lastUser = [...messages]
                          .reverse()
                          .find(message => message.role === 'user');
                        if (lastUser && lastUser.role === 'user') {
                          snippetSource = lastUser.text.trim();
                        }
                      }
                      const fileNames = new Set<string>();
                      for (const message of messages) {
                        if (message.role === 'user') {
                          for (const name of message.attachmentNames ?? []) fileNames.add(name);
                        } else if (message.document?.meta.source_refs) {
                          for (const name of displaySourceRefs(message.document.meta.source_refs)) {
                            fileNames.add(name);
                          }
                        }
                      }
                      return {
                        ...thread,
                        snippet: cleanHistorySnippet(snippetSource),
                        files: [...fileNames].map(filename => ({
                          filename,
                          meta: attachmentTypeLabel(filename),
                        })),
                      };
                    })}
                    activeThreadId={threadId}
                    pinnedThreadIds={pinnedThreadIds}
                    userId={userId}
                    orgId={orgId}
                    onOpenThread={id => {
                      navigateShell('chat');
                      handleSelectThread(id);
                    }}
                    onNewChat={handleNewThread}
                    onClose={() => navigateShell('chat')}
                    onRenameThread={openRenameThread}
                    onPinThread={handlePinThreadTop}
                    onDeleteThread={(id, title) => setArchiveTarget({ id, title })}
                    onDeleteThreads={items => {
                      if (items.length === 1) {
                        const only = items[0];
                        if (only) setArchiveTarget(only);
                        return;
                      }
                      setBulkArchive(items);
                    }}
                  />
                </Suspense>
              ) : null}
              {shellView === 'project-create' ? (
                <Suspense fallback={<div className="market-page__loading" aria-busy="true" />}>
                  <CreateProjectPage busy={false} onCreate={handleCreateProject} />
                </Suspense>
              ) : null}
              {shellView === 'project' && messages.length === 0 ? (
                <Suspense fallback={<div className="market-page__loading" aria-busy="true" />}>
                  <ProjectWorkspacePage
                    title={
                      projects.find(p => p.id === projectId)?.title?.trim() || t('sidebar.untitled')
                    }
                    onAddFiles={files => addFiles(Array.from(files))}
                    onRename={() => openRenameProject(projectId)}
                    onPinTop={() => pinProjectTop(projectId)}
                    onDelete={() => {
                      const title =
                        projects.find(p => p.id === projectId)?.title?.trim() ||
                        t('sidebar.untitled');
                      setProjectDelete({ id: projectId, title });
                    }}
                  />
                </Suspense>
              ) : null}
              {isChatSurface(shellView) && !(shellView === 'project' && messages.length === 0) ? (
                <div className={`transcript-with-nav${showDialogueNav ? ' has-dialogue-nav' : ''}`}>
                  {showDialogueNav ? (
                    <DialogueNav entries={dialogueNavEntries} scrollRootRef={transcriptRef} />
                  ) : null}
                  <MessageList ref={transcriptRef} label={t('a11y.transcript')}>
                    {messages.map(message => {
                      if (message.role === 'user') {
                        return (
                          <div
                            key={message.id}
                            id={dialogueTurnDomId(message.id)}
                            data-turn-id={message.id}
                            className="msg user"
                          >
                            <div className="bubble-col">
                              {message.attachmentNames && message.attachmentNames.length > 0 ? (
                                <ul
                                  className="user-file-list"
                                  aria-label={t('composer.attachedFiles')}
                                >
                                  {message.attachmentNames.map((name, index) => {
                                    const attachmentId = message.attachmentIds?.[index];
                                    const ext = name.includes('.')
                                      ? (name.split('.').pop()?.toUpperCase() ?? '')
                                      : '';
                                    return (
                                      <li key={attachmentId ?? name}>
                                        <UserAttachmentCard
                                          filename={name}
                                          meta={ext}
                                          active={
                                            filesRail?.mode === 'preview' &&
                                            filesRail.id === attachmentId
                                          }
                                          openLabel={t('attach.openFile', { name })}
                                          onOpen={
                                            attachmentId
                                              ? () => openAttachmentPreview(attachmentId, name)
                                              : undefined
                                          }
                                        />
                                      </li>
                                    );
                                  })}
                                </ul>
                              ) : null}
                              <div className="bubble">
                                <p>{message.text}</p>
                              </div>
                              <UserMessageActions
                                onEdit={() => editUserMessage(message)}
                                onCopy={() => copyUserMessage(message)}
                                disabled={busy}
                              />
                            </div>
                          </div>
                        );
                      }

                      const pendingHitl = (message.hitlCards ?? []).filter(
                        card => card.status === 'pending'
                      );
                      const showHitl = pendingHitl.length > 0;
                      const showDevGap =
                        devMode &&
                        !showHitl &&
                        looksLikeExclusiveMenu(message.document) &&
                        message._requiresReview;
                      const sourceChips = message.document
                        ? displaySourceRefs(message.document.meta.source_refs)
                        : [];
                      // Провайдерские якоря точнее чипов из `source_refs`: если они есть, показываем
                      // их (с цитатами), иначе — прежний список имён файлов.
                      const citationAnchors = message.document?.meta.citations ?? [];
                      const documentIsArtifact =
                        Boolean(message.document) &&
                        isArtifactWorthy(message.document as ContentDocument);
                      const answerSourceNames = sourceChips.length
                        ? sourceChips
                        : citationAnchors.map(citation => citation.source_ref);
                      const primaryAnswerFile =
                        answerSourceNames
                          .map(ref => {
                            const refFp = sourceRefFingerprint(ref);
                            return threadAttachments.find(file => {
                              const fileFp = sourceRefFingerprint(file.filename);
                              return (
                                file.filename === ref ||
                                (Boolean(refFp) && refFp === fileFp) ||
                                ref.endsWith(file.filename) ||
                                file.filename.endsWith(ref)
                              );
                            });
                          })
                          .find(Boolean) ?? null;
                      /* Source chips already open the same files — skip primary card duplicate. */
                      const primaryAlreadyChipped =
                        primaryAnswerFile != null &&
                        answerSourceNames.some(ref => {
                          const refFp = sourceRefFingerprint(ref);
                          const fileFp = sourceRefFingerprint(primaryAnswerFile.filename);
                          return Boolean(refFp) && refFp === fileFp;
                        });

                      const isStreamingBubble =
                        Boolean(message._streaming) ||
                        (Boolean(message._regenerating) &&
                          streamingAssistantIdRef.current === message.id);
                      const showStreamPreview = isStreamingBubble && !message.document;
                      /**
                       * Ожидание без единого токена: в ленте не «облако с подписью», а
                       * только орб текущей фазы (паттерн Big Tech). Как только приходит
                       * заголовок/первый блок — это уже предпросмотр ответа, т.е. облако.
                       */
                      const isWaiting =
                        showStreamPreview && !streamDocument && streamPreview.length === 0;

                      return (
                        <div
                          key={message.id}
                          className={`msg assistant${showStreamPreview ? ' pending' : ''}${
                            isWaiting ? ' is-waiting' : ''
                          }`}
                          style={
                            streamBubbleMinHeight && streamingAssistantIdRef.current === message.id
                              ? { minHeight: streamBubbleMinHeight }
                              : undefined
                          }
                        >
                          {isWaiting ? (
                            <ThinkingIndicator phase={pendingPhase} />
                          ) : (
                            <>
                              <AssistantAvatar />
                              <div
                                className="bubble bubble--plain"
                                ref={
                                  showStreamPreview ||
                                  streamingAssistantIdRef.current === message.id
                                    ? streamBubbleRef
                                    : undefined
                                }
                              >
                                {showStreamPreview ? (
                                  streamDocument ? (
                                    <div className="stream-preview stream-preview--doc">
                                      <BlockRenderer document={streamDocument} />
                                    </div>
                                  ) : (
                                    <StreamMarkdownPreview markdown={streamPreview} />
                                  )
                                ) : message.document ? (
                                  <>
                                    {/*
                                Product chat follows Kimi: answer prose first, then actions.
                                Revision chrome (W7b note + block wash) is operator-only —
                                end users read the final answer, not a diff dashboard.
                              */}
                                    {devMode ? <RevisionNote revision={message.revision} /> : null}
                                    <BlockRenderer
                                      document={message.document}
                                      revision={devMode ? message.revision : null}
                                    />
                                    {citationAnchors.length > 0 ? (
                                      <CitationSources
                                        citations={citationAnchors}
                                        userId={userId}
                                        orgId={orgId}
                                        onOpenPdfPage={openAttachmentPreview}
                                      />
                                    ) : sourceChips.length > 0 ? (
                                      <ul
                                        className="source-ref-chips"
                                        aria-label={t('attach.sources')}
                                      >
                                        {sourceChips.map((ref, index) => {
                                          const refFp = sourceRefFingerprint(ref);
                                          const matched = threadAttachments.find(file => {
                                            const fileFp = sourceRefFingerprint(file.filename);
                                            return (
                                              file.filename === ref ||
                                              (Boolean(refFp) && refFp === fileFp) ||
                                              ref.endsWith(file.filename) ||
                                              file.filename.endsWith(ref)
                                            );
                                          });
                                          return (
                                            <li
                                              key={ref}
                                              id={`source-ref-${index + 1}`}
                                              className="source-ref-chip"
                                            >
                                              {matched ? (
                                                <button
                                                  type="button"
                                                  className="source-ref-button"
                                                  onClick={() =>
                                                    openAttachmentPreview(
                                                      matched.id,
                                                      matched.filename
                                                    )
                                                  }
                                                  aria-label={t('attach.openFile', {
                                                    name: matched.filename,
                                                  })}
                                                >
                                                  <span className="source-ref-icon" aria-hidden>
                                                    <AttachmentFileIcon
                                                      kind={attachmentFileKind(matched.filename)}
                                                      size={18}
                                                    />
                                                  </span>
                                                  <span className="source-ref-name">{ref}</span>
                                                </button>
                                              ) : (
                                                <>
                                                  <span className="source-ref-icon" aria-hidden>
                                                    <AttachmentFileIcon
                                                      kind={attachmentFileKind(ref)}
                                                      size={18}
                                                    />
                                                  </span>
                                                  <span className="source-ref-name">{ref}</span>
                                                </>
                                              )}
                                            </li>
                                          );
                                        })}
                                      </ul>
                                    ) : null}
                                    {/*
                                Anthropic/Kimi: file/artifact pills only under substantial
                                answers — never under short social/ack (isArtifactWorthy).
                                Sticky thread attachments alone must not paint cards.
                              */}
                                    {documentIsArtifact ? (
                                      <AnswerFileCards
                                        artifactTitle={message.document?.title}
                                        artifactActive={artifactMessageId === message.id}
                                        onOpenArtifact={() => {
                                          setFilesRail(null);
                                          setArtifactMessageId(message.id);
                                        }}
                                        primaryFile={
                                          primaryAnswerFile && !primaryAlreadyChipped
                                            ? {
                                                id: primaryAnswerFile.id,
                                                filename: primaryAnswerFile.filename,
                                              }
                                            : null
                                        }
                                        primaryActive={
                                          filesRail?.mode === 'preview' &&
                                          primaryAnswerFile !== null &&
                                          !primaryAlreadyChipped &&
                                          filesRail.id === primaryAnswerFile.id
                                        }
                                        onOpenPrimary={openAttachmentPreview}
                                        showAllFiles={threadAttachments.length > 0}
                                        allFilesActive={filesRail?.mode === 'list'}
                                        onOpenAllFiles={openAttachmentsList}
                                      />
                                    ) : null}
                                    {showHitl ? (
                                      <HitlCards
                                        cards={pendingHitl}
                                        userId={userId}
                                        orgId={orgId}
                                        onResolved={event => handleHitlResolved(message.id, event)}
                                      />
                                    ) : null}
                                    {showDevGap && (
                                      <p className="hitl-dev-gap">{t('msg.devGap')}</p>
                                    )}
                                    {message.error && <p className="msg-error">{message.error}</p>}
                                    {!showHitl ? (
                                      <MessageActions
                                        onCopy={() => copyMessageContent(message)}
                                        onShare={() => void shareMessageContent(message)}
                                        onRegenerate={() => void regenerateResponse(message.id)}
                                        onLike={() => handleFeedback(message.id, 'like')}
                                        onDislike={() => handleFeedback(message.id, 'dislike')}
                                        liked={!!message._feedbackLike}
                                        disliked={!!message._feedbackDislike}
                                        regenerating={!!message._regenerating}
                                        disabled={busy || !!message._feedbackSending}
                                      />
                                    ) : null}
                                    {devMode ? (
                                      <span className="dev-meta">
                                        Confidence: {message.document.meta.confidence} | Requires
                                        review: {String(message._requiresReview)}
                                      </span>
                                    ) : null}
                                  </>
                                ) : showHitl ? (
                                  <HitlCards
                                    cards={pendingHitl}
                                    userId={userId}
                                    orgId={orgId}
                                    onResolved={event => handleHitlResolved(message.id, event)}
                                  />
                                ) : (
                                  <p className="msg-error">
                                    {message.error ?? t('msg.emptyResponse')}
                                  </p>
                                )}
                              </div>
                            </>
                          )}
                        </div>
                      );
                    })}
                    <div ref={messageEndRef} />
                  </MessageList>
                </div>
              ) : null}
            </div>

            {isChatSurface(shellView) ? (
              <div
                className={`composer-dock${shellView === 'project' ? ' composer-dock--project' : ''}`}
                data-zone="ZONE_FOOTER"
              >
                {messages.length > 0 && !isAtThreadEnd ? (
                  <IconButton
                    className="scroll-bottom-fab"
                    aria-label={t('thread.scrollBottom')}
                    title={t('thread.scrollBottom')}
                    onClick={() =>
                      messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
                    }
                  >
                    <IconChevronDown size={16} />
                  </IconButton>
                ) : null}
                {messages.length === 0 &&
                (isHomeView(shellView) || shellView === 'deep-research') ? (
                  <div
                    className={`composer-hero${LOGO_VIEWS.has(shellView) ? '' : ' is-logo-hidden'}`}
                    data-zone="ZONE_HERO"
                    aria-hidden={!LOGO_VIEWS.has(shellView)}
                  >
                    <div className="composer-hero__live">
                      <BrandWordmark />
                    </div>
                  </div>
                ) : null}
                <Composer
                  input={input}
                  onInputChange={setInput}
                  onSubmit={() => void send()}
                  onStop={() => streamAbortRef.current?.abort()}
                  busy={busy}
                  canSend={canSend}
                  overLimit={overLimit}
                  inputLength={inputLength}
                  nearLimit={nearLimit}
                  counterClass={counterClass}
                  counterLive={counterLive}
                  hasMessages={messages.length > 0}
                  showToolBar={messages.length === 0 && shellView !== 'project'}
                  deepResearchMode={shellView === 'deep-research' && messages.length === 0}
                  onExitDeepResearch={() => navigateShell('chat')}
                  onExitProductMode={() => navigateShell('chat')}
                  placeholderOverride={productPlaceholder(
                    shellView,
                    projects.find(p => p.id === projectId)?.title
                  )}
                  dragActive={dragActive}
                  onDragOver={e => {
                    e.preventDefault();
                    setDragActive(true);
                  }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={e => {
                    e.preventDefault();
                    setDragActive(false);
                    addFiles(Array.from(e.dataTransfer.files));
                  }}
                  onPaste={handleComposerPaste}
                  fileInputRef={fileInputRef}
                  composerInputRef={composerInputRef}
                  attachmentAccept={ATTACHMENT_ACCEPT}
                  onFilesSelected={files => addFiles(files)}
                  projectId={projectId}
                  projects={projects.map(proj => ({ id: proj.id, title: proj.title }))}
                  onProjectChange={id => {
                    if (id) setProjectId(id);
                    else setProjectId('');
                  }}
                  onRequestCreateProject={() => navigateShell('project-create')}
                  intensity={intensity}
                  contextLength={contextLength}
                  onIntensityChange={setIntensity}
                  onContextLengthChange={setContextLength}
                  onOpenPluginsPage={() => navigateShell('plugins')}
                  webSearchMode={webSearchPref}
                  onSlashAction={action => {
                    if (action.kind === 'skills') navigateShell('skills');
                    else if (action.kind === 'goal') navigateShell('scheduled');
                    else if (action.kind === 'webSearch') {
                      setWebSearchPref(action.mode);
                      setModeIntent(action.mode === 'auto' ? 'web_search' : null);
                    } else if (action.kind === 'plugin')
                      toast(t('plugins.installSoon', { name: action.id }));
                  }}
                  productMode={
                    PRODUCT_MODES[shellView]
                      ? {
                          label: t(PRODUCT_MODES[shellView]!.labelKey),
                          icon: PRODUCT_MODES[shellView]!.icon,
                        }
                      : undefined
                  }
                  showEmptyChrome={messages.length === 0}
                  productChips={
                    messages.length === 0 && shellView === 'chat' ? (
                      <ProductChips
                        chips={productChips}
                        onSelect={id => {
                          const view = CHIP_VIEWS[id];
                          if (view) navigateShell(view);
                        }}
                      />
                    ) : null
                  }
                  landingTail={
                    messages.length === 0 ? (
                      shellView === 'deep-research' ? (
                        <FeaturedResearchCases
                          onSelect={title => {
                            setInput(t('chip.prompt.deepResearch') + title);
                            composerInputRef.current?.focus();
                          }}
                        />
                      ) : isHomeView(shellView) && shellView !== 'chat' ? (
                        <ProductShowcase
                          key={shellView}
                          view={shellView}
                          onSelectPrompt={prompt => {
                            setInput(prompt);
                            composerInputRef.current?.focus();
                          }}
                        />
                      ) : null
                    ) : null
                  }
                  attachmentSlot={
                    attachments.length > 0 ? (
                      <ul
                        className="attachment-chips attachment-chips--in-capsule"
                        aria-label={t('composer.attachedFiles')}
                      >
                        {attachments.map(chip => {
                          const tip = chip.error ?? attachmentDisplayName(chip.filename);
                          const pending = chip.status === 'uploading' || chip.status === 'scanning';
                          const kind = attachmentFileKind(chip.filename);
                          const isThumb = kind === 'image' && Boolean(chip.previewUrl);
                          const meta = chip.error
                            ? chip.error
                            : pending
                              ? chip.status === 'uploading'
                                ? t('attach.uploading')
                                : t('attach.waiting')
                              : attachmentChipMeta(chip.filename, chip.sizeBytes);
                          return (
                            <li
                              key={chip.localId}
                              className={
                                'attachment-chip is-' +
                                chip.status +
                                (chip.origin === 'paste' ? ' is-paste' : '') +
                                (isThumb ? ' attachment-chip--thumb' : '')
                              }
                              data-tooltip={tip}
                            >
                              {isThumb ? (
                                <img
                                  className="attachment-chip__thumb"
                                  src={chip.previewUrl}
                                  alt=""
                                  draggable={false}
                                />
                              ) : (
                                <>
                                  <span className="attachment-chip__icon" aria-hidden>
                                    <AttachmentFileIcon kind={kind} size={44} />
                                  </span>
                                  <span className="attachment-chip__text">
                                    <span className="attachment-name">
                                      {attachmentDisplayName(chip.filename)}
                                    </span>
                                    <span className="attachment-size">
                                      {pending ? <IconLoader className="spin" size={14} /> : null}
                                      <span className="attachment-size__label">{meta}</span>
                                    </span>
                                  </span>
                                </>
                              )}
                              <button
                                type="button"
                                className="attachment-remove"
                                onClick={() => removeAttachment(chip.localId)}
                                aria-label={t('composer.removeAttachment', { name: chip.filename })}
                              >
                                <IconX size={12} />
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    ) : null
                  }
                  toolsSlot={
                    messages.length > 0 ? (
                      <div className="composer-context is-open">
                        <MemoryActions
                          threadId={threadId}
                          userId={userId}
                          orgId={orgId}
                          disabled={busy}
                          onCardCreated={handleMemoryCardCreated}
                        />
                      </div>
                    ) : null
                  }
                />
              </div>
            ) : null}
          </div>

          {canResizeSideConsole ? (
            <SideConsoleResizer
              workspaceRef={workspaceRef}
              widthPercent={sideConsoleWidthPct}
              onWidthPercentChange={setSideConsoleWidth}
              onReset={resetSideConsoleWidth}
            />
          ) : null}

          {filesRail ? (
            <FilePreviewPane
              mode={filesRail.mode}
              files={threadAttachments}
              attachmentId={filesRail.mode === 'preview' ? filesRail.id : null}
              filename={filesRail.mode === 'preview' ? filesRail.filename : null}
              initialPage={filesRail.mode === 'preview' ? (filesRail.page ?? null) : null}
              userId={userId}
              orgId={orgId}
              onClose={() => setFilesRail(null)}
              onSelectFile={openAttachmentPreview}
              onShowList={openAttachmentsList}
            />
          ) : artifactMessage?.document ? (
            <ArtifactPane
              document={artifactMessage.document}
              revision={artifactMessage.revision}
              messageId={artifactMessage.id}
              userId={userId}
              orgId={orgId}
              busy={busy}
              feedbackLike={artifactMessage._feedbackLike}
              feedbackDislike={artifactMessage._feedbackDislike}
              feedbackSending={artifactMessage._feedbackSending}
              regenerating={artifactMessage._regenerating}
              onClose={() => setArtifactMessageId(null)}
              onLike={() => handleFeedback(artifactMessage.id, 'like')}
              onDislike={() => handleFeedback(artifactMessage.id, 'dislike')}
              onCopy={() => copyMessageContent(artifactMessage)}
              onShare={() => void shareMessageContent(artifactMessage)}
              onExportPdf={() => {
                if (!artifactMessage.document) return;
                void downloadDocumentPdf(artifactMessage.document, threadId, userId, orgId).catch(
                  (err: unknown) => {
                    toast.error(t('toast.pdfFailed'));
                    console.error(err);
                  }
                );
              }}
              onRegenerate={() => void regenerateResponse(artifactMessage.id)}
            />
          ) : null}
        </div>
      </div>

      {/* Канал озвучивания живёт ВНЕ ленты: `aria-live="off"` на ленте гасит
          объявления от изменений документа, но не должен гасить прогресс. */}
      <LiveAnnouncer announcement={a11yAnnouncement} />

      <KimiDialog
        open={renameTarget !== null}
        title={t('sidebar.rename')}
        closeLabel={t('dialog.close')}
        onClose={() => setRenameTarget(null)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              onClick={() => setRenameTarget(null)}
            >
              {t('dialog.close')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--primary"
              disabled={renameBusy || !renameDraft.trim()}
              onClick={() => void submitRenameThread()}
            >
              {t('sidebar.renameSave')}
            </button>
          </>
        }
      >
        <div className="kimi-field">
          <label className="kimi-field__label" htmlFor="rename-thread-title">
            {t('sidebar.rename')}
          </label>
          <input
            id="rename-thread-title"
            className="kimi-field__input"
            type="text"
            maxLength={255}
            value={renameDraft}
            data-autofocus
            onChange={e => setRenameDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void submitRenameThread();
              }
            }}
          />
        </div>
      </KimiDialog>

      <KimiDialog
        open={archiveTarget !== null}
        title={t('sidebar.delete')}
        description={t('sidebar.deleteConfirm', {
          title: archiveTarget?.title ?? t('sidebar.untitled'),
        })}
        closeLabel={t('dialog.close')}
        onClose={() => setArchiveTarget(null)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              onClick={() => setArchiveTarget(null)}
            >
              {t('dialog.close')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--danger"
              disabled={archiveBusy}
              onClick={() => void submitArchiveThread()}
            >
              {t('sidebar.delete')}
            </button>
          </>
        }
      />

      <KimiDialog
        open={bulkArchive !== null}
        title={t('historyPage.bulkDelete')}
        description={t('historyPage.bulkDeleteConfirm', {
          count: bulkArchive?.length ?? 0,
        })}
        closeLabel={t('dialog.close')}
        onClose={() => setBulkArchive(null)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              onClick={() => setBulkArchive(null)}
            >
              {t('dialog.close')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--danger"
              disabled={archiveBusy}
              onClick={() => void submitBulkArchive()}
            >
              {t('historyPage.bulkDelete')}
            </button>
          </>
        }
      />

      <KimiDialog
        open={projectRename !== null}
        title={t('project.rename.title')}
        closeLabel={t('dialog.close')}
        onClose={() => setProjectRename(null)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              onClick={() => setProjectRename(null)}
            >
              {t('dialog.close')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--primary"
              disabled={projectRenameBusy || !projectRenameDraft.trim()}
              onClick={() => void submitRenameProject()}
            >
              {t('project.rename.save')}
            </button>
          </>
        }
      >
        <div className="kimi-field">
          <label className="kimi-field__label" htmlFor="rename-project-title">
            {t('project.rename.title')}
          </label>
          <input
            id="rename-project-title"
            className="kimi-field__input"
            type="text"
            maxLength={255}
            value={projectRenameDraft}
            data-autofocus
            onChange={e => setProjectRenameDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void submitRenameProject();
              }
            }}
          />
        </div>
      </KimiDialog>

      <KimiDialog
        open={projectDelete !== null}
        title={t('project.action.delete')}
        description={t('project.action.deleteConfirm', {
          title: projectDelete?.title ?? t('sidebar.untitled'),
        })}
        closeLabel={t('dialog.close')}
        onClose={() => setProjectDelete(null)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              onClick={() => setProjectDelete(null)}
            >
              {t('dialog.close')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--danger"
              disabled={projectDeleteBusy}
              onClick={() => void submitDeleteProject()}
            >
              {t('project.action.delete')}
            </button>
          </>
        }
      />
    </div>
  );
}
