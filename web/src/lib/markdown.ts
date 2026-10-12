/**
 * Streaming Markdown helpers: close dangling markers + prepare icon tokens for preview.
 */

import type { IconToken } from '../types/contentDocument';

/** Matches `<icon name="…"/>` and legacy LLM slip `<icon x="…"/>`. */
export const ICON_TOKEN = /<icon\s+(?:name|x)="([a-z_]+)"\s*\/>/gi;

const HITL_TAG = /<\/?hitl-(?:action|choice)\b[^>]*\/?>/gi;

/**
 * Emoji / VS16 / ZWJ runs. FE0F and 200D are matched as separate alternates
 * (not inside the class) to satisfy ``no-misleading-character-class``.
 */
const EMOJI_RUN =
  /(?:[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}\u{2600}-\u{26FF}]|\u{FE0F}|\u{200D})+/gu;

/** Opaque markdown image target — StreamMarkdownPreview maps to TokenIcon. */
export const ICON_MD_SCHEME = 'palatium-icon:';

const ICON_NAME_SET = new Set<string>([
  'calendar',
  'mail',
  'search',
  'document',
  'warning',
  'success',
  'danger',
  'info',
  'user',
  'users',
  'clock',
  'chart',
  'shield',
  'check',
  'x',
  'link',
  'edit',
  'settings',
]);

/**
 * Close incomplete markdown constructs so react-markdown does not collapse
 * half a table / bold / fence mid-stream. Idempotent on a complete buffer.
 */
export function closeDanglingMarkdown(text: string): string {
  if (!text) return text;

  let result = text;

  const fenceCount = (result.match(/^```/gm) ?? []).length;
  if (fenceCount % 2 === 1) {
    result += '\n```';
  }

  const withoutFences = result.replace(/```[\s\S]*?```/g, '');
  const ticks = (withoutFences.match(/(?<!\\)`/g) ?? []).length;
  if (ticks % 2 === 1) {
    result += '`';
  }

  const boldPairs = (withoutFences.match(/(?<!\\)\*\*/g) ?? []).length;
  if (boldPairs % 2 === 1) {
    result += '**';
  }

  const singles = withoutFences.replace(/\*\*/g, '').match(/(?<!\\)\*/g) ?? [];
  if (singles.length % 2 === 1) {
    result += '*';
  }

  const openBrackets = (withoutFences.match(/\[/g) ?? []).length;
  const closeBrackets = (withoutFences.match(/\]/g) ?? []).length;
  if (openBrackets > closeBrackets) {
    result += ']';
  }

  return result;
}

/** Coerce a raw icon name to a known IconToken, or null. */
export function coerceIconToken(raw: string | null | undefined): IconToken | null {
  if (!raw) return null;
  const name = raw.trim().toLowerCase();
  return ICON_NAME_SET.has(name) ? (name as IconToken) : null;
}

/**
 * Parse ``palatium-icon:NAME`` from a markdown image ``src`` produced by
 * {@link prepareStreamMarkdown}.
 */
export function iconTokenFromMdSrc(src: string | undefined): IconToken | null {
  if (!src?.startsWith(ICON_MD_SCHEME)) return null;
  return coerceIconToken(src.slice(ICON_MD_SCHEME.length));
}

/** Remove icon tokens (defense-in-depth / non-preview paths). Accepts name= and x=. */
export function stripIconTokens(markdown: string): string {
  return markdown.replace(ICON_TOKEN, '');
}

/**
 * Replace ``<icon name|x="…"/>`` with a markdown image that the preview
 * ``img`` component turns into {@link TokenIcon}. Unknown names stay as
 * ``palatium-icon:unknown`` so the renderer can fall back without raw tags.
 */
export function iconTokensToMarkdownImages(markdown: string): string {
  return markdown.replace(ICON_TOKEN, (_match, name: string) => {
    const raw = name.trim().toLowerCase() || 'unknown';
    const token = coerceIconToken(raw) ?? raw;
    return `![icon](${ICON_MD_SCHEME}${token})`;
  });
}

/**
 * Preview sanitize: strip HITL + emoji, keep icons as markdown images, close dangling.
 * Does **not** strip icon tokens — preview renders them via TokenIcon.
 */
export function sanitizeStreamMarkdown(markdown: string): string {
  return closeDanglingMarkdown(
    iconTokensToMarkdownImages(
      markdown.replace(HITL_TAG, '').replace(EMOJI_RUN, '').replace(/\n{3,}/g, '\n\n').trim()
    )
  );
}
