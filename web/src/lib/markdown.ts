/**
 * Streaming Markdown helpers: close dangling markers + strip non-preview tokens.
 */

const ICON_TOKEN = /<icon\s+name="[a-z_]+"\s*\/>/gi;
const HITL_TAG = /<\/?hitl-(?:action|choice)\b[^>]*\/?>/gi;
const EMOJI_RUN =
  /[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}\u{2600}-\u{26FF}\u{FE0F}\u{200D}]+/gu;

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

/** Remove `<icon name="…"/>` from stream preview (final BlockRenderer draws library icons). */
export function stripIconTokens(markdown: string): string {
  return markdown.replace(ICON_TOKEN, '');
}

/** Remove HITL XML + icon tokens + leftover emoji from progressive preview. */
export function sanitizeStreamMarkdown(markdown: string): string {
  return closeDanglingMarkdown(
    markdown
      .replace(HITL_TAG, '')
      .replace(ICON_TOKEN, '')
      .replace(EMOJI_RUN, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  );
}
