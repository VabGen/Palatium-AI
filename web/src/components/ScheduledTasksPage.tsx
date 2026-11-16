import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import cronLight from '../assets/cron-light.svg';
import {
  IconAddConversation,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPencil,
  IconX,
} from '../icons/kimiStroke';
import { formatDateTime, t } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import { KimiMenu } from './ui/KimiDropdown';
import { PopoverSurface } from './ui/PopoverSurface';

export type ScheduledTasksPageProps = {
  /** Route a ready-made instruction into the chat composer (no silent scheduling). */
  onCompose: (prompt: string) => void;
};

type Cadence = 'daily' | 'weekly' | 'monthly' | 'once';
type ModelId = 'standard' | 'instant';

const CADENCE_OPTIONS: readonly { id: Cadence; label: MessageKey }[] = [
  { id: 'daily', label: 'scheduled.cadence.daily' },
  { id: 'weekly', label: 'scheduled.cadence.weekly' },
  { id: 'monthly', label: 'scheduled.cadence.monthly' },
  { id: 'once', label: 'scheduled.cadence.once' },
];

const MODEL_OPTIONS: readonly { id: ModelId; label: MessageKey }[] = [
  { id: 'standard', label: 'scheduled.model.standard' },
  { id: 'instant', label: 'scheduled.model.instant' },
];

const WEEKDAY_LABELS: readonly MessageKey[] = [
  'scheduled.weekday.mon',
  'scheduled.weekday.tue',
  'scheduled.weekday.wed',
  'scheduled.weekday.thu',
  'scheduled.weekday.fri',
  'scheduled.weekday.sat',
  'scheduled.weekday.sun',
];

const WEEKDAY_SHORT: readonly MessageKey[] = [
  'scheduled.weekdayShort.mon',
  'scheduled.weekdayShort.tue',
  'scheduled.weekdayShort.wed',
  'scheduled.weekdayShort.thu',
  'scheduled.weekdayShort.fri',
  'scheduled.weekdayShort.sat',
  'scheduled.weekdayShort.sun',
];

const NAME_MAX = 50;
const DAYS_IN_MONTH = 31;

const pad2 = (value: number): string => String(value).padStart(2, '0');

/** Next full hour — a schedule set "for now" would be rejected server-side. */
function nextHourTime(): string {
  const next = new Date(Date.now() + 60 * 60 * 1000);
  return `${pad2(next.getHours())}:00`;
}

function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year || 2000, (month || 1) - 1, day || 1);
}

function isoDateDaysAhead(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return toIsoDate(date);
}

function formatDay(iso: string): string {
  return formatDateTime(parseIsoDate(iso), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

function formatMonth(date: Date): string {
  return formatDateTime(date, { month: 'long', year: 'numeric' });
}

type PopoverTriggerProps = {
  label: string;
  trigger: ReactNode;
  children: (close: () => void) => ReactNode;
  panelClassName?: string;
  className?: string;
  align?: 'start' | 'end';
};

/** Field-level dropdown: Kimi popover surface anchored to its own trigger. */
function FieldPopover({
  label,
  trigger,
  children,
  panelClassName = '',
  className = '',
  align = 'start',
}: PopoverTriggerProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  return (
    <div className={`task-pop ${className}`.trim()} ref={rootRef}>
      <button
        type="button"
        className="task-pop__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen(v => !v)}
      >
        {trigger}
        <IconChevronDown size={14} className="task-pop__chevron" />
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        align={align}
        className={`kimi-menu task-pop__panel ${panelClassName}`.trim()}
        role="menu"
        label={label}
        onDismiss={close}
      >
        {children(close)}
      </PopoverSurface>
    </div>
  );
}

/** Scrollable numeric column (hours / minutes / day of month). */
function NumberColumn({
  values,
  selected,
  label,
  onSelect,
}: {
  values: readonly string[];
  selected: string;
  label: string;
  onSelect: (value: string) => void;
}) {
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' });
  }, []);

  return (
    <ul className="task-picker__col" role="group" aria-label={label}>
      {values.map(value => {
        const active = value === selected;
        return (
          <li key={value}>
            <button
              type="button"
              ref={active ? selectedRef : undefined}
              className={`task-picker__option${active ? ' is-active' : ''}`}
              aria-pressed={active}
              onClick={() => onSelect(value)}
            >
              {value}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

const HOURS = Array.from({ length: 24 }, (_, index) => pad2(index));
const MINUTES = Array.from({ length: 60 }, (_, index) => pad2(index));
const MONTH_DAYS = Array.from({ length: DAYS_IN_MONTH }, (_, index) => String(index + 1));

function TimePopover({
  value,
  label,
  onChange,
}: {
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  const [hour = '09', minute = '00'] = value.split(':');

  return (
    <FieldPopover
      label={label}
      panelClassName="task-picker task-picker--time"
      trigger={<span className="task-pop__value">{value}</span>}
    >
      {close => (
        <div className="task-picker__cols">
          <NumberColumn
            values={HOURS}
            selected={hour}
            label={t('scheduled.hour')}
            onSelect={next => onChange(`${next}:${minute}`)}
          />
          <NumberColumn
            values={MINUTES}
            selected={minute}
            label={t('scheduled.minute')}
            onSelect={next => {
              onChange(`${hour}:${next}`);
              close();
            }}
          />
        </div>
      )}
    </FieldPopover>
  );
}

function DayPopover({
  value,
  label,
  onChange,
}: {
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  return (
    <FieldPopover
      label={label}
      panelClassName="task-picker task-picker--days"
      trigger={<span className="task-pop__value">{value}</span>}
    >
      {close => (
        <NumberColumn
          values={MONTH_DAYS}
          selected={value}
          label={label}
          onSelect={next => {
            onChange(next);
            close();
          }}
        />
      )}
    </FieldPopover>
  );
}

function WeekdayPopover({
  value,
  label,
  onChange,
}: {
  value: number;
  label: string;
  onChange: (value: number) => void;
}) {
  return (
    <FieldPopover
      label={label}
      panelClassName="task-picker task-picker--weekday"
      trigger={<span className="task-pop__value">{t(WEEKDAY_LABELS[value])}</span>}
    >
      {close => (
        <ul className="task-picker__list" role="none">
          {WEEKDAY_LABELS.map((weekday, index) => {
            const active = index === value;
            return (
              <li key={weekday}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  className={`task-picker__item${active ? ' is-active' : ''}`}
                  onClick={() => {
                    onChange(index);
                    close();
                  }}
                >
                  <span>{t(weekday)}</span>
                  {active ? <IconCheck size={14} /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </FieldPopover>
  );
}

function DatePopover({
  value,
  label,
  onChange,
}: {
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  const selected = parseIsoDate(value);
  const [month, setMonth] = useState(
    () => new Date(selected.getFullYear(), selected.getMonth(), 1)
  );
  const [todayIso] = useState(() => toIsoDate(new Date()));

  const shiftMonth = (delta: number) => {
    setMonth(prev => new Date(prev.getFullYear(), prev.getMonth() + delta, 1));
  };

  const year = month.getFullYear();
  const monthIndex = month.getMonth();
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  // Monday-first grid: weekday of the 1st, shifted from Sunday-based getDay().
  const leading = (new Date(year, monthIndex, 1).getDay() + 6) % 7;
  const cells: (string | null)[] = [
    ...Array.from({ length: leading }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) =>
      toIsoDate(new Date(year, monthIndex, index + 1))
    ),
  ];

  return (
    <FieldPopover
      label={label}
      panelClassName="task-picker task-picker--calendar"
      trigger={<span className="task-pop__value">{formatDay(value)}</span>}
    >
      {close => (
        <div className="task-calendar">
          <div className="task-calendar__head">
            <button
              type="button"
              className="task-calendar__nav"
              aria-label={t('scheduled.prevMonth')}
              onClick={() => shiftMonth(-1)}
            >
              <IconChevronRight size={14} className="task-calendar__nav--prev" />
            </button>
            <span className="task-calendar__month">{formatMonth(month)}</span>
            <button
              type="button"
              className="task-calendar__nav"
              aria-label={t('scheduled.nextMonth')}
              onClick={() => shiftMonth(1)}
            >
              <IconChevronRight size={14} />
            </button>
          </div>
          <div className="task-calendar__grid">
            {WEEKDAY_SHORT.map(day => (
              <span key={day} className="task-calendar__weekday">
                {t(day)}
              </span>
            ))}
            {cells.map((iso, index) =>
              iso ? (
                <button
                  key={iso}
                  type="button"
                  className={[
                    'task-calendar__day',
                    iso === value ? 'is-selected' : '',
                    iso === todayIso ? 'is-today' : '',
                  ]
                    .join(' ')
                    .trim()}
                  aria-pressed={iso === value}
                  onClick={() => {
                    onChange(iso);
                    close();
                  }}
                >
                  {parseIsoDate(iso).getDate()}
                </button>
              ) : (
                <span key={`blank-${WEEKDAY_SHORT[index]}`} className="task-calendar__blank" />
              )
            )}
          </div>
        </div>
      )}
    </FieldPopover>
  );
}

function ModelPopover({
  value,
  label,
  onChange,
}: {
  value: ModelId;
  label: string;
  onChange: (value: ModelId) => void;
}) {
  const selected = MODEL_OPTIONS.find(option => option.id === value) ?? MODEL_OPTIONS[0];

  return (
    <FieldPopover
      label={label}
      panelClassName="task-picker--model"
      className="task-pop--wide"
      trigger={<span className="task-pop__value">{t(selected.label)}</span>}
    >
      {close => (
        <ul className="task-picker__list" role="none">
          {MODEL_OPTIONS.map(option => {
            const active = option.id === value;
            return (
              <li key={option.id}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  className={`task-picker__item${active ? ' is-active' : ''}`}
                  onClick={() => {
                    onChange(option.id);
                    close();
                  }}
                >
                  <span>{t(option.label)}</span>
                  {active ? <IconCheck size={14} /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </FieldPopover>
  );
}

/**
 * Kimi `/tasks` — Scheduled tasks surface.
 *
 * The product has no client-side scheduler: scheduled runs are server jobs
 * (CronJob / one-shot, ADR 0002), so both creation paths hand the request to
 * the orchestrator through chat. Nothing is persisted locally and no "saved"
 * state is shown before the assistant confirms the task — a fake stored list
 * here would be a silent, unbacked write.
 */
export function ScheduledTasksPage({ onCompose }: ScheduledTasksPageProps) {
  const [manualOpen, setManualOpen] = useState(false);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState<ModelId>('standard');
  const [cadence, setCadence] = useState<Cadence>('daily');
  const [time, setTime] = useState(nextHourTime);
  const [weekday, setWeekday] = useState(() => (new Date().getDay() + 6) % 7);
  const [monthDay, setMonthDay] = useState(() => String(new Date().getDate()));
  const [onceDate, setOnceDate] = useState(() => isoDateDaysAhead(7));
  const [expiresAt, setExpiresAt] = useState(() => isoDateDaysAhead(30));
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const composeViaChat = () => {
    onCompose(t('scheduled.prompt'));
  };

  const openManual = () => {
    setError(null);
    setManualOpen(true);
  };

  const closeManual = useCallback(() => setManualOpen(false), []);

  useEffect(() => {
    if (!manualOpen) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    nameRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setManualOpen(false);
        return;
      }
      if (event.key !== 'Tab') return;
      const root = modalRef.current;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter(element => element.offsetParent !== null);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus?.();
    };
  }, [manualOpen]);

  const scheduleSummary = useMemo(() => {
    if (cadence === 'weekly') {
      return t('scheduled.summary.weekly', { weekday: t(WEEKDAY_LABELS[weekday]), time });
    }
    if (cadence === 'monthly') {
      return t('scheduled.summary.monthly', { day: monthDay, time });
    }
    if (cadence === 'once') {
      return t('scheduled.summary.once', { date: formatDay(onceDate), time });
    }
    return t('scheduled.summary.daily', { time });
  }, [cadence, monthDay, onceDate, time, weekday]);

  const submitManual = () => {
    const taskName = name.trim();
    const instruction = prompt.trim();
    if (!taskName) {
      setError(t('scheduled.requiredName'));
      nameRef.current?.focus();
      return;
    }
    if (!instruction) {
      setError(t('scheduled.requiredPrompt'));
      return;
    }
    const modelLabel = t(
      MODEL_OPTIONS.find(option => option.id === model)?.label ?? 'scheduled.model.standard'
    );
    onCompose(
      t('scheduled.manualTemplate', {
        name: taskName,
        prompt: instruction,
        schedule: scheduleSummary,
        model: modelLabel,
        expiration: formatDay(expiresAt),
      })
    );
    setManualOpen(false);
    setName('');
    setPrompt('');
    setError(null);
  };

  return (
    <div className="task-page" data-zone="ZONE_BODY">
      <header className="task-header">
        <div className="task-header__heading">
          <h1 className="task-header__title">{t('scheduled.title')}</h1>
          <p className="task-header__subtitle">{t('scheduled.subtitle')}</p>
        </div>

        <div className="task-create-group">
          <button type="button" className="task-create-main" onClick={openManual}>
            {t('scheduled.create')}
          </button>
          <KimiMenu
            label={t('scheduled.createMenu')}
            align="end"
            triggerClassName="task-create-arrow"
            menuClassName="task-create-menu"
            trigger={<IconChevronDown size={18} />}
          >
            <button
              type="button"
              className="task-create-menu__item"
              role="menuitem"
              onClick={composeViaChat}
            >
              <IconAddConversation size={16} />
              <span>{t('scheduled.createViaChat')}</span>
            </button>
            <button
              type="button"
              className="task-create-menu__item"
              role="menuitem"
              onClick={openManual}
            >
              <IconPencil size={16} />
              <span>{t('scheduled.createManual')}</span>
            </button>
          </KimiMenu>
        </div>
      </header>

      <div className="task-empty">
        <img className="task-empty__art" src={cronLight} width={120} height={120} alt="" />
        {/* kimi.ai `.task-empty-copy`: headline line, then the two creation paths. */}
        <div className="task-empty__copy">
          <p>{t('scheduled.emptyTitle')}</p>
          <p>
            <button type="button" className="task-empty__link" onClick={openManual}>
              {t('scheduled.addManually')}
            </button>{' '}
            {t('scheduled.or')}{' '}
            <button type="button" className="task-empty__link" onClick={composeViaChat}>
              {t('scheduled.createViaChat')}
            </button>
          </p>
        </div>
      </div>

      {manualOpen
        ? createPortal(
            <div
              className="modal-mask"
              role="presentation"
              onMouseDown={event => {
                if (event.target === event.currentTarget) closeManual();
              }}
            >
              <div
                ref={modalRef}
                className="create-task-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="create-task-title"
              >
                <header className="create-task-modal__head">
                  <h2 id="create-task-title" className="create-task-modal__title">
                    {t('scheduled.manualTitle')}
                  </h2>
                  <button
                    type="button"
                    className="create-task-modal__close"
                    aria-label={t('dialog.close')}
                    onClick={closeManual}
                  >
                    <IconX size={18} />
                  </button>
                </header>

                <div className="create-task-modal__body">
                  <div className="task-field">
                    <div className="task-field__top">
                      <label className="task-field__label" htmlFor="task-name">
                        {t('scheduled.field.name')}
                      </label>
                      <span className="task-field__count">
                        {name.length}/{NAME_MAX}
                      </span>
                    </div>
                    <input
                      id="task-name"
                      ref={nameRef}
                      className="task-field__input"
                      type="text"
                      maxLength={NAME_MAX}
                      value={name}
                      placeholder={t('scheduled.namePlaceholder')}
                      aria-invalid={error ? true : undefined}
                      onChange={event => {
                        setName(event.target.value);
                        if (error) setError(null);
                      }}
                    />
                  </div>

                  <div className="task-field">
                    <label className="task-field__label" htmlFor="task-prompt">
                      {t('scheduled.field.prompt')}
                    </label>
                    <textarea
                      id="task-prompt"
                      className="task-field__input task-field__input--area"
                      rows={4}
                      value={prompt}
                      placeholder={t('scheduled.promptPlaceholder')}
                      aria-invalid={error ? true : undefined}
                      onChange={event => {
                        setPrompt(event.target.value);
                        if (error) setError(null);
                      }}
                    />
                  </div>

                  <div className="task-field">
                    <span className="task-field__label">{t('scheduled.field.model')}</span>
                    <ModelPopover
                      value={model}
                      label={t('scheduled.field.model')}
                      onChange={setModel}
                    />
                  </div>

                  <div className="task-field">
                    <span className="task-field__label">{t('scheduled.field.schedule')}</span>
                    <div className="task-schedule">
                      <div
                        className="task-schedule__tabs"
                        role="radiogroup"
                        aria-label={t('scheduled.field.schedule')}
                      >
                        {CADENCE_OPTIONS.map(option => {
                          const active = option.id === cadence;
                          return (
                            <button
                              key={option.id}
                              type="button"
                              role="radio"
                              aria-checked={active}
                              className={`task-schedule__tab${active ? ' is-active' : ''}`}
                              onClick={() => setCadence(option.id)}
                            >
                              {t(option.label)}
                            </button>
                          );
                        })}
                      </div>

                      <div className="task-schedule__controls">
                        {cadence === 'once' ? (
                          <DatePopover
                            value={onceDate}
                            label={t('scheduled.field.date')}
                            onChange={setOnceDate}
                          />
                        ) : null}
                        {cadence === 'weekly' ? (
                          <WeekdayPopover
                            value={weekday}
                            label={t('scheduled.field.weekday')}
                            onChange={setWeekday}
                          />
                        ) : null}
                        {cadence === 'monthly' ? (
                          <DayPopover
                            value={monthDay}
                            label={t('scheduled.field.monthDay')}
                            onChange={setMonthDay}
                          />
                        ) : null}
                        <TimePopover
                          value={time}
                          label={t('scheduled.field.time')}
                          onChange={setTime}
                        />
                      </div>
                      <p className="task-schedule__summary">{scheduleSummary}</p>
                    </div>
                  </div>

                  <div className="task-field">
                    <span className="task-field__label">{t('scheduled.field.expiration')}</span>
                    <DatePopover
                      value={expiresAt}
                      label={t('scheduled.field.expiration')}
                      onChange={setExpiresAt}
                    />
                  </div>

                  {error ? (
                    <p className="task-field__error" role="alert">
                      {error}
                    </p>
                  ) : null}
                </div>

                <footer className="create-task-modal__foot">
                  <button type="button" className="task-btn task-btn--ghost" onClick={closeManual}>
                    {t('scheduled.cancel')}
                  </button>
                  <button
                    type="button"
                    className="task-btn task-btn--primary"
                    onClick={submitManual}
                  >
                    {t('scheduled.save')}
                  </button>
                </footer>
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
