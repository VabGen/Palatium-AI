import type { ActionKind, CalloutTone, IconToken, StepStatus } from '../types/contentDocument';

/**
 * Деривация иконки из семантических полей блока.
 * Применяется только когда явный `icon` у блока = null.
 * Приоритет: block.icon ?? iconFor*(...)
 *
 * Живёт отдельно от `TokenIcon`: атом не знает про CalloutBlock / StepItem /
 * ActionSpec, деривацию вызывают рендереры блоков.
 */

const TONE_TO_ICON: Record<CalloutTone, IconToken> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
};

const STEP_STATUS_TO_ICON: Record<StepStatus, IconToken> = {
  pending: 'clock',
  active: 'clock',
  done: 'success',
  blocked: 'x',
};

const ACTION_KIND_TO_ICON: Record<ActionKind, IconToken | null> = {
  approve: 'check',
  reject: 'x',
  confirm: 'check',
  dismiss: 'x',
  custom: null, // без деривации — рендерер решает сам
  format: 'edit',
};

export const iconForTone = (t: CalloutTone): IconToken => TONE_TO_ICON[t];

/**
 * Иконка шага — про **состояние процесса**, а не про тему пункта.
 * Нет статуса → нет иконки: маркер рисует порядковый номер, то есть ровно то,
 * что известно из данных. Иначе перечень пунктов получал бы «часы» у каждой
 * строки — одинаковый и не по теме значок.
 */
export const iconForStepStatus = (s: StepStatus | null | undefined): IconToken | null =>
  s == null ? null : STEP_STATUS_TO_ICON[s];

export const iconForActionKind = (k: ActionKind): IconToken | null => ACTION_KIND_TO_ICON[k];
