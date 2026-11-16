import { describe, expect, it } from 'vitest';

import {
  buildDialogueNavEntries,
  buildDialogueNavLabel,
  dialogueTurnDomId,
  endEllipsis,
  midEllipsis,
  shouldShowDialogueNav,
} from '../../src/lib/dialogueNav';

describe('dialogueNav helpers', () => {
  it('builds turn dom ids', () => {
    expect(dialogueTurnDomId('abc')).toBe('turn-abc');
  });

  it('mid-ellipsis keeps head and tail', () => {
    expect(midEllipsis('Сканирование.pdf', 10)).toMatch(/…/);
    expect(midEllipsis('short', 10)).toBe('short');
  });

  it('end-ellipsis truncates long prompts', () => {
    expect(endEllipsis('a'.repeat(40), 10).endsWith('…')).toBe(true);
  });

  it('keeps file chip + count + full prompt for CSS ellipsis', () => {
    const entries = buildDialogueNavEntries([
      {
        id: '1',
        role: 'user',
        text: 'сравни файлы по ключевым условиям договора',
        attachmentNames: ['Скан1.pdf', 'Скан2.pdf'],
      },
    ]);
    const entry = entries[0];
    expect(entry?.extraCount).toBe(1);
    expect(entry?.fileName).toBe('Скан1.pdf');
    expect(entry?.prompt).toBe('сравни файлы по ключевым условиям договора');
    expect(entry?.label).toContain('+1');
    expect(entry?.label).toContain('сравни файлы');
  });

  it('plain text turns use no file chip and skip below threshold', () => {
    const one = buildDialogueNavEntries([{ id: '1', role: 'user', text: 'привет' }]);
    expect(shouldShowDialogueNav(one)).toBe(false);
    expect(one[0]?.hasFile).toBe(false);
    expect(one[0]?.fileName).toBeNull();

    const entries = buildDialogueNavEntries([
      { id: '1', role: 'user', text: 'о чем файл', attachmentNames: ['табл2026.xlsx'] },
      { id: 'a', role: 'assistant', text: '…' },
      { id: '2', role: 'user', text: 'дай анализ скан1' },
    ]);
    expect(entries).toHaveLength(2);
    expect(entries[0]?.iconKind).toBe('xlsx');
    expect(entries[0]?.hasFile).toBe(true);
    expect(entries[0]?.fileName).toBe('табл2026.xlsx');
    expect(entries[0]?.prompt).toBe('о чем файл');
    expect(entries[1]?.hasFile).toBe(false);
    expect(entries[1]?.prompt).toBe('дай анализ скан1');
    expect(shouldShowDialogueNav(entries)).toBe(true);
  });

  it('soft-caps only extreme pastes; short titles stay intact', () => {
    const label = buildDialogueNavLabel('короткий', []);
    expect(label).toBe('короткий');
  });
});
