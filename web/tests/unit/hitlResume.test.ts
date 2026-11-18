import { describe, expect, it } from 'vitest';
import {
  displayTextForUserTurn,
  isHitlChoiceResumeText,
  tryParseHitlChoiceResume,
} from '../../src/lib/hitlResume';

const ENVELOPE =
  '<<<HITL_CHOICE_RESUME kind=clarify action_id=filesel_1 option_kind=custom>>>\n' +
  '<<<UNTRUSTED_HITL_LABEL\nДоговор оказания услуг.docx\n<<<END_UNTRUSTED_HITL_LABEL>>>';

describe('hitlResume', () => {
  it('detects resume envelopes', () => {
    expect(isHitlChoiceResumeText(ENVELOPE)).toBe(true);
    expect(isHitlChoiceResumeText('обычный вопрос')).toBe(false);
  });

  it('parses kind / action_id / label', () => {
    const parsed = tryParseHitlChoiceResume(ENVELOPE);
    expect(parsed).toEqual({
      resumeKind: 'clarify',
      actionId: 'filesel_1',
      optionKind: 'custom',
      label: 'Договор оказания услуг.docx',
    });
  });

  it('accepts collapsed whitespace between label fences', () => {
    const collapsed =
      '<<<HITL_CHOICE_RESUME kind=clarify action_id=filesel_1 option_kind=custom>>> ' +
      '<<<UNTRUSTED_HITL_LABEL Договор оказания услуг.docx <<<END_UNTRUSTED_HITL_LABEL>>>';
    expect(tryParseHitlChoiceResume(collapsed)?.label).toBe('Договор оказания услуг.docx');
  });

  it('displayTextForUserTurn shows only the label', () => {
    expect(displayTextForUserTurn(ENVELOPE)).toBe('Договор оказания услуг.docx');
    expect(displayTextForUserTurn('сравни файлы')).toBe('сравни файлы');
  });

  it('hides corrupt envelopes instead of dumping markers', () => {
    expect(displayTextForUserTurn('<<<HITL_CHOICE_RESUME kind=clarify>>>')).toBe('');
  });
});
