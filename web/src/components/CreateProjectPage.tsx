import { useId, useState, type FormEvent } from 'react';
import { t } from '../i18n';

export type CreateProjectPageProps = {
  busy?: boolean;
  onCreate: (title: string) => void | Promise<void>;
};

/**
 * Folder silhouette for ``/project/create`` — kimi.ai ``project-create-file`` shape
 * (tabbed folder, 210×183 artboard). Brand mark is product name, not KIMI.
 */
function ProjectFolderArt({ mark }: { mark?: string }) {
  return (
    <svg
      className="project-create__folder-art"
      viewBox="0 0 210 183"
      width="100%"
      height="100%"
      aria-hidden
    >
      <path
        className="project-create__folder-body"
        d="M28 42c0-8.284 6.716-15 15-15h48.2c4.2 0 8.1 1.9 10.7 5.1l8.1 10.1c2.6 3.2 6.5 5.1 10.7 5.1H167c8.284 0 15 6.716 15 15v96c0 8.284-6.716 15-15 15H43c-8.284 0-15-6.716-15-15V42Z"
        fill="var(--bg-elevated)"
        stroke="color-mix(in srgb, var(--kimi-ink, var(--text)) 18%, transparent)"
        strokeWidth="2.5"
      />
      <path
        className="project-create__folder-lip"
        d="M43 72.5h124"
        fill="none"
        stroke="color-mix(in srgb, var(--kimi-ink, var(--text)) 12%, transparent)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {mark ? (
        <text
          className="project-create__folder-mark-text"
          x="40"
          y="148"
          fill="color-mix(in srgb, var(--kimi-ink, var(--text)) 28%, transparent)"
          fontFamily="var(--font-display), system-ui, sans-serif"
          fontSize="14"
          fontWeight="600"
          letterSpacing="1.2"
        >
          {mark}
        </text>
      ) : null}
    </svg>
  );
}

type SideSlot = 'outer-left' | 'inner-left' | 'inner-right' | 'outer-right';

const SIDE_SLOTS: readonly SideSlot[] = ['outer-left', 'inner-left', 'inner-right', 'outer-right'];

/**
 * kimi.ai ``/project/create`` — title, folder carousel (CSS grid stack), name + Create.
 * Hero hover: ``rotate(-6deg) scale(1.05)`` — slight tilt, not a flip (DevTools 2026-11-11).
 * Color System: tokens only.
 */
export function CreateProjectPage({ busy = false, onCreate }: CreateProjectPageProps) {
  const [title, setTitle] = useState('');
  const inputId = useId();
  const trimmed = title.trim();
  const canSubmit = trimmed.length > 0 && !busy;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    void Promise.resolve(onCreate(trimmed));
  };

  return (
    <section className="project-create" data-zone="ZONE_BODY" aria-labelledby={inputId}>
      <header className="project-create__header">
        <h1 className="project-create__title">{t('project.create.title')}</h1>
        <p className="project-create__subtitle">{t('project.create.subtitle')}</p>
      </header>

      <div className="project-create__illustration" aria-hidden>
        {SIDE_SLOTS.map(slot => (
          <div key={slot} className={`project-create__folder is-${slot}`}>
            <ProjectFolderArt />
          </div>
        ))}
        <div className="project-create__folder is-hero">
          <ProjectFolderArt mark="PALATIUM" />
        </div>
      </div>

      <form className="project-create__form" onSubmit={submit}>
        <label className="sr-only" htmlFor={inputId}>
          {t('project.create.nameLabel')}
        </label>
        <div className="project-create__field">
          <input
            id={inputId}
            type="text"
            className="project-create__input"
            value={title}
            maxLength={255}
            placeholder={t('project.create.namePlaceholder')}
            autoFocus
            disabled={busy}
            onChange={e => setTitle(e.target.value)}
          />
          <button type="submit" className="project-create__submit" disabled={!canSubmit}>
            {t('project.create.submit')}
          </button>
        </div>
      </form>
    </section>
  );
}
