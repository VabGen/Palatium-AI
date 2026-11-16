import { attachmentFileKind, type FileTypeKind } from '../icons/fileTypeIcons';

/** Minimum user turns before the Kimi-style jump rail appears. */
export const DIALOGUE_NAV_MIN_ENTRIES = 2;

/**
 * Safety cap only — visual truncation is CSS ``text-overflow: ellipsis`` so the
 * chip fills the real row width (char budgets left empty space / double-cut).
 */
export const DIALOGUE_NAV_TEXT_SAFE_MAX = 160;

export type DialogueNavSource = {
  id: string;
  role: string;
  text?: string;
  attachmentNames?: readonly string[];
};

export type DialogueNavEntry = {
  id: string;
  /** Accessible name for the jump button (full, unclipped for screen readers). */
  label: string;
  /** First attachment basename; absent for text-only turns. */
  fileName: string | null;
  extraCount: number;
  /** User prompt (whitespace-normalised); CSS ellipsis owns overflow. */
  prompt: string;
  iconKind: FileTypeKind;
  hasFile: boolean;
};

export function dialogueTurnDomId(messageId: string): string {
  return `turn-${messageId}`;
}

export function midEllipsis(value: string, max: number): string {
  const text = value.trim();
  if (text.length <= max) return text;
  if (max < 5) return `${text.slice(0, Math.max(0, max - 1))}…`;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`;
}

export function endEllipsis(value: string, max: number): string {
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1))}…`;
}

function normalisePrompt(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim();
}

/** Soft ceiling so a paste bomb cannot inflate the DOM; UI still CSS-clips. */
function softCap(value: string, max = DIALOGUE_NAV_TEXT_SAFE_MAX): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

export function buildDialogueNavEntries(
  messages: readonly DialogueNavSource[]
): DialogueNavEntry[] {
  const entries: DialogueNavEntry[] = [];
  for (const message of messages) {
    if (message.role !== 'user') continue;
    const names = message.attachmentNames ?? [];
    const promptRaw = normalisePrompt(message.text ?? '');
    const hasFile = names.length > 0;
    const fileName = hasFile ? softCap(names[0] ?? '', DIALOGUE_NAV_TEXT_SAFE_MAX) : null;
    const extraCount = Math.max(0, names.length - 1);
    const prompt = softCap(promptRaw);
    const labelParts = [
      fileName,
      extraCount > 0 ? `+${extraCount}` : null,
      prompt || null,
    ].filter(Boolean);
    entries.push({
      id: message.id,
      label: labelParts.join(' ') || '…',
      fileName,
      extraCount,
      prompt,
      iconKind: names[0] ? attachmentFileKind(names[0]) : 'text',
      hasFile,
    });
  }
  return entries;
}

export function shouldShowDialogueNav(entries: readonly DialogueNavEntry[]): boolean {
  return entries.length >= DIALOGUE_NAV_MIN_ENTRIES;
}

/** @deprecated Prefer structured fields + CSS ellipsis; kept for helper unit coverage. */
export function buildDialogueNavLabel(
  text: string,
  attachmentNames: readonly string[] = [],
  max = 34
): string {
  const entry = buildDialogueNavEntries([
    { id: 'x', role: 'user', text, attachmentNames },
  ])[0];
  if (!entry) return endEllipsis(text, max);
  return entry.label.length <= max ? entry.label : endEllipsis(entry.label, max);
}
