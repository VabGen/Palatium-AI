import { useEffect, useId, useRef, useState } from 'react';
import { KimiGlyph } from '../icons/kimiNavGlyphs';
import { IconCheck, IconFolder } from '../icons/kimiStroke';
import { PopoverSurface } from './ui/PopoverSurface';
import { t } from '../i18n';

export type ProjectMenuItem = { id: string; title: string };

export type ProjectMenuProps = {
  projects: readonly ProjectMenuItem[];
  projectId: string;
  onSelect: (id: string) => void;
  /** kimi.ai: «New project» navigates to `/project/create`, not an inline form. */
  onRequestCreate?: () => void;
  disabled?: boolean;
};

/**
 * Composer «Выбрать проект» menu — kimi.ai `.kimi-menu` structure:
 * project rows (18px folder + name), 0.5px divider, «New project», then
 * «Don't use project» with a trailing `--Colors-KMBlue` check on the active row.
 */
export function ProjectMenu({
  projects,
  projectId,
  onSelect,
  onRequestCreate,
  disabled,
}: ProjectMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const selected = projects.find(p => p.id === projectId);
  const label = selected ? selected.title : t('composer.bar.selectProject');

  const close = () => setOpen(false);

  return (
    <div className="project-menu" ref={rootRef}>
      <button
        type="button"
        className={`composer-bar__btn icon-hover${open ? ' is-open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => {
          if (open) close();
          else setOpen(true);
        }}
      >
        <IconFolder size={18} />
        <span>{label}</span>
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        id={menuId}
        className="project-menu__panel"
        role="menu"
        onDismiss={() => setOpen(false)}
        onEscape={() => setOpen(false)}
      >
        {projects.map(project => {
          const active = projectId === project.id;
          return (
            <button
              key={project.id}
              type="button"
              role="menuitemradio"
              aria-checked={active}
              className={`kimi-dd__item${active ? ' is-selected' : ''}`}
              onClick={() => {
                onSelect(project.id);
                close();
              }}
            >
              <span className="project-menu__icon" aria-hidden>
                <IconFolder size={18} />
              </span>
              <span className="project-menu__label">{project.title}</span>
              {active ? (
                <span className="project-menu__check" aria-hidden>
                  <IconCheck size={20} />
                </span>
              ) : null}
            </button>
          );
        })}
        {/* kimi.ai: divider only when project rows sit above New / Don't use. */}
        {projects.length > 0 ? <div className="project-menu__divider" aria-hidden /> : null}
        {onRequestCreate ? (
          <button
            type="button"
            role="menuitem"
            className="kimi-dd__item"
            onClick={() => {
              close();
              onRequestCreate();
            }}
          >
            <span className="project-menu__icon" aria-hidden>
              <KimiGlyph name="addFolder" size={18} />
            </span>
            <span className="project-menu__label">{t('sidebar.createProject')}</span>
          </button>
        ) : null}
        <button
          type="button"
          role="menuitemradio"
          aria-checked={!projectId}
          className={`kimi-dd__item${!projectId ? ' is-selected' : ''}`}
          onClick={() => {
            onSelect('');
            close();
          }}
        >
          <span className="project-menu__icon" aria-hidden>
            <KimiGlyph name="noFolder" size={18} />
          </span>
          <span className="project-menu__label">{t('composer.project.none')}</span>
          {!projectId ? (
            <span className="project-menu__check" aria-hidden>
              <IconCheck size={20} />
            </span>
          ) : null}
        </button>
      </PopoverSurface>
    </div>
  );
}
