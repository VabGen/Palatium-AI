/**
 * Close incomplete markdown constructs for streaming pending preview (FOIM).
 * Final UI still uses ContentDocument / BlockRenderer — this is preview-only.
 */

export function closeIncompleteMarkdown(text: string): string {
  if (!text) return text;

  let result = text;

  // Unclosed fenced code block
  const fenceCount = (result.match(/^```/gm) ?? []).length;
  if (fenceCount % 2 === 1) {
    result += '\n```';
  }

  // Unclosed inline code (odd number of unescaped backticks outside fences)
  const withoutFences = result.replace(/```[\s\S]*?```/g, '');
  const ticks = (withoutFences.match(/(?<!\\)`/g) ?? []).length;
  if (ticks % 2 === 1) {
    result += '`';
  }

  // Unclosed bold (**)
  const boldPairs = (withoutFences.match(/(?<!\\)\*\*/g) ?? []).length;
  if (boldPairs % 2 === 1) {
    result += '**';
  }

  // Unclosed italic single * (ignore **)
  const singles = withoutFences.replace(/\*\*/g, '').match(/(?<!\\)\*/g) ?? [];
  if (singles.length % 2 === 1) {
    result += '*';
  }

  // Unclosed link '[' without ']'
  const openBrackets = (withoutFences.match(/\[/g) ?? []).length;
  const closeBrackets = (withoutFences.match(/\]/g) ?? []).length;
  if (openBrackets > closeBrackets) {
    result += ']';
  }

  return result;
}
