/**
 * Display helpers for server-minted HITL choice resume envelopes.
 *
 * Live clicks never paint the machine text (ChatShell updates the assistant
 * bubble in place). After ``fetchDialogTurns`` the envelope is a normal user
 * turn — show the fenced label only, never the ``<<<HITL_…>>>`` markers.
 *
 * Contract mirrors ``ChoiceResumePolicy`` in
 * ``src/palatium_ai/domain/hitl/choice_resume.py``.
 */

const HITL_RESUME_MARKER = 'HITL_CHOICE_RESUME';

const RESUME_HEADER_RE =
  /<<<HITL_CHOICE_RESUME\s+kind=(?<kind>format|tool|clarify)\s+action_id=(?<action_id>[^\s>]+)\s+option_kind=(?<option_kind>[^\s>]+)\s*>>>/;

/** Lenient label fence: newlines optional (whitespace may collapse in UI). */
const LABEL_BLOCK_RE =
  /<<<UNTRUSTED_HITL_LABEL\s*\r?\n?(?<label>[\s\S]*?)\r?\n?\s*<<<END_UNTRUSTED_HITL_LABEL>>>/;

export type ParsedHitlChoiceResume = {
  resumeKind: 'format' | 'tool' | 'clarify';
  actionId: string;
  optionKind: string;
  label: string;
};

export function isHitlChoiceResumeText(text: string): boolean {
  return text.includes(HITL_RESUME_MARKER);
}

export function tryParseHitlChoiceResume(text: string): ParsedHitlChoiceResume | null {
  const stripped = text.trim();
  if (!stripped.includes(HITL_RESUME_MARKER)) return null;
  const header = RESUME_HEADER_RE.exec(stripped);
  if (!header?.groups) return null;
  const labelMatch = LABEL_BLOCK_RE.exec(stripped);
  const label = labelMatch?.groups?.label?.trim() ?? '';
  if (!label) return null;
  const kind = header.groups.kind;
  if (kind !== 'format' && kind !== 'tool' && kind !== 'clarify') return null;
  return {
    resumeKind: kind,
    actionId: header.groups.action_id.slice(0, 120),
    optionKind: header.groups.option_kind.slice(0, 40),
    label: label.slice(0, 200),
  };
}

/**
 * User-bubble / dialogue-nav text for a turn. Resume envelopes → human label;
 * anything else passes through unchanged.
 */
export function displayTextForUserTurn(text: string): string {
  if (!isHitlChoiceResumeText(text)) return text;
  const parsed = tryParseHitlChoiceResume(text);
  if (parsed) return parsed.label;
  // Corrupt / partial envelope — never dump machine markers into the UI.
  return '';
}
