/** Client-only main stage view (no React Router). */
export type ShellView =
  | 'chat'
  | 'deep-research'
  | 'plugins'
  | 'skills'
  | 'scheduled'
  | 'history'
  | 'pricing'
  | 'settings'
  | 'slides'
  | 'make3d'
  | 'build'
  | 'docs'
  | 'sheets'
  | 'design'
  | 'work'
  | 'code'
  | 'claw'
  | 'platform'
  | 'project-create'
  | 'project';

export const SHELL_VIEWS: readonly ShellView[] = [
  'chat',
  'deep-research',
  'plugins',
  'skills',
  'scheduled',
  'history',
  'pricing',
  'settings',
  'slides',
  'make3d',
  'build',
  'docs',
  'sheets',
  'design',
  'work',
  'code',
  'claw',
  'platform',
  'project-create',
  'project',
];

/**
 * Views that render the Kimi home stage (wordmark + composer + shortcuts).
 * kimi.ai serves `/slides`, `/make3d`, `/build`, `/docs`, `/sheets`, `/design`
 * as the same landing surface with a product preset — not a separate app shell.
 */
/** Surfaces that reuse the home stage. Cut products are not home landings. */
export const HOME_VIEWS: readonly ShellView[] = ['chat', 'slides', 'docs', 'sheets', 'claw'];

export function isShellView(value: string): value is ShellView {
  return (SHELL_VIEWS as readonly string[]).includes(value);
}

export function isHomeView(view: ShellView): boolean {
  return HOME_VIEWS.includes(view);
}

/** Chat surface = home landing, deep research, or an open project workspace. */
export function isChatSurface(view: ShellView): boolean {
  return isHomeView(view) || view === 'deep-research' || view === 'project';
}

function hashPath(hash: string): string {
  return hash.replace(/^#\/?/, '').split('?')[0]?.toLowerCase() ?? '';
}

/**
 * Optional standalone hash sync:
 * `#/plugins` | `#/skills` | `#/deep-research` | `#/scheduled`
 * | `#/history` | `#/pricing` | `#/project/create` | `#/project/:id` | `#/`
 */
export function shellViewFromHash(hash: string): ShellView {
  const path = hashPath(hash);
  if (!path) return 'chat';
  if (path === 'my' || path === 'mykimi') return 'chat';
  if (path === 'chat' || path.startsWith('chat/')) return 'chat';
  /* Billing / plan / membership — not a product surface. */
  if (path === 'pricing' || path.startsWith('membership/') || path === 'upgrade') return 'chat';
  /* Product cuts: Inspiration / 3D Make / Build / Design / Work / Code / Open Platform. */
  if (
    path === 'inspiration' ||
    path.startsWith('inspiration/') ||
    path === 'make3d' ||
    path.startsWith('make3d/') ||
    path === 'build' ||
    path.startsWith('build/') ||
    path === 'design' ||
    path.startsWith('design/') ||
    path === 'work' ||
    path.startsWith('work/') ||
    path === 'code' ||
    path.startsWith('code/') ||
    path === 'platform' ||
    path.startsWith('platform/')
  ) {
    return 'chat';
  }
  if (path === 'project/create' || path.startsWith('project/create/')) return 'project-create';
  if (path.startsWith('project/')) return 'project';
  if (isShellView(path) && path !== 'pricing') return path;
  if (path.startsWith('plugins/')) return 'plugins';
  if (path.startsWith('skills/')) return 'skills';
  if (path.startsWith('deep-research/')) return 'deep-research';
  if (path.startsWith('scheduled/') || path === 'tasks') return 'scheduled';
  if (path.startsWith('history/') || path === 'chats') return 'history';
  if (path.startsWith('settings')) return 'settings';
  return 'chat';
}

/** `#/project/{id}` → id; create / bare project → null. */
export function projectIdFromHash(hash: string): string | null {
  const path = hash.replace(/^#\/?/, '').split('?')[0] ?? '';
  const match = /^project\/([^/]+)/i.exec(path);
  if (!match) return null;
  const id = decodeURIComponent(match[1] ?? '');
  if (!id || id.toLowerCase() === 'create') return null;
  return id;
}

export function hashForProjectCreate(): string {
  return '#/project/create';
}

export function hashForProject(projectId: string): string {
  return `#/project/${encodeURIComponent(projectId)}`;
}

/** Settings sections live in the hash so a section is linkable (`#/settings/chat`). */
export const SETTINGS_SECTION_IDS = [
  'account',
  'notifications',
  'appearance',
  'speech',
  'shortcuts',
  'features',
  'subscription',
  'billing',
  'gift-cards',
  'memory',
  'chat',
  'prompts',
] as const;

export type SettingsSectionId = (typeof SETTINGS_SECTION_IDS)[number];

export function isSettingsSectionId(value: string): value is SettingsSectionId {
  return (SETTINGS_SECTION_IDS as readonly string[]).includes(value);
}

const BILLING_SETTINGS_SECTIONS = new Set<SettingsSectionId>([
  'subscription',
  'billing',
  'gift-cards',
]);

export function settingsSectionFromHash(hash: string): SettingsSectionId {
  const tail = hash.replace(/^#\/?/, '').split('?')[0]?.split('/')[1]?.toLowerCase() ?? '';
  if (!isSettingsSectionId(tail) || BILLING_SETTINGS_SECTIONS.has(tail)) return 'account';
  return tail;
}

/** Hash for a settings section: `#/settings/appearance` (account is the default). */
export function hashForSettingsSection(section: SettingsSectionId): string {
  return `#/settings/${section}`;
}

export function hashForShellView(view: ShellView): string {
  if (view === 'chat') return '#/';
  if (view === 'settings') return hashForSettingsSection('account');
  if (view === 'project-create') return hashForProjectCreate();
  /* Concrete project needs an id — callers use hashForProject(id). */
  if (view === 'project') return hashForProjectCreate();
  return `#/${view}`;
}
