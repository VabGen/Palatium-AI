import { useId, useRef, useState } from 'react';
import {
  IconFileText,
  IconMoreHorizontal,
  IconPencil,
  IconPin,
  IconPlus,
  IconTrash,
} from '../icons/kimiStroke';
import { KimiGlyph } from '../icons/kimiNavGlyphs';
import { t } from '../i18n';
import { KimiDialog } from './KimiDialog';
import { KimiMenu } from './ui/KimiDropdown';

export type ProjectWorkspacePageProps = {
  title: string;
  onAddFiles?: (files: FileList) => void;
  onRename?: () => void;
  onPinTop?: () => void;
  onDelete?: () => void;
};

/**
 * kimi.ai `/project/{id}` empty workspace — shared-context hero + Instructions / Files cards.
 * Header More = Edit project name / Pin to top / Delete (observed 2026-11-09).
 */
export function ProjectWorkspacePage({
  title,
  onAddFiles,
  onRename,
  onPinTop,
  onDelete,
}: ProjectWorkspacePageProps) {
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [instructions, setInstructions] = useState('');
  const [savedInstructions, setSavedInstructions] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const instructionsId = useId();

  const openInstructions = () => {
    setInstructions(savedInstructions);
    setInstructionsOpen(true);
  };

  const saveInstructions = () => {
    setSavedInstructions(instructions.trim());
    setInstructionsOpen(false);
  };

  return (
    <section className="project-workspace" data-zone="ZONE_BODY">
      <header className="project-workspace__header">
        <span className="project-workspace__folder" aria-hidden>
          <KimiGlyph name="folder" size={28} />
        </span>
        <h1 className="project-workspace__title" data-name-tip={title}>
          {title}
        </h1>
        <div className="project-workspace__actions">
          {onRename ? (
            <button
              type="button"
              className="project-workspace__icon-btn icon-hover"
              aria-label={t('project.action.rename')}
              title={t('project.action.rename')}
              onClick={onRename}
            >
              <IconPencil size={18} />
            </button>
          ) : null}
          <KimiMenu
            label={t('thread.more')}
            align="end"
            placement="bottom"
            triggerClassName="project-workspace__icon-btn"
            trigger={<IconMoreHorizontal size={16} />}
          >
            <button
              type="button"
              className="kimi-dd__item"
              role="menuitem"
              onClick={() => onRename?.()}
            >
              <IconPencil size={18} />
              <span className="kimi-dd__item-label">{t('project.action.rename')}</span>
            </button>
            <button
              type="button"
              className="kimi-dd__item"
              role="menuitem"
              onClick={() => onPinTop?.()}
            >
              <IconPin size={16} />
              <span className="kimi-dd__item-label">{t('project.action.pin')}</span>
            </button>
            <button
              type="button"
              className="kimi-dd__item kimi-dd__item--danger"
              role="menuitem"
              onClick={() => onDelete?.()}
            >
              <IconTrash size={18} />
              <span className="kimi-dd__item-label">{t('project.action.delete')}</span>
            </button>
          </KimiMenu>
        </div>
      </header>

      <div className="project-workspace__layout">
        <div className="project-workspace__hero">
          <div className="project-workspace__orb" aria-hidden>
            <span className="project-workspace__orb-bubble" />
          </div>
          <p className="project-workspace__lead">{t('project.workspace.lead')}</p>
          <p className="project-workspace__hint">{t('project.workspace.hint')}</p>
        </div>

        <aside className="project-workspace__cards" aria-label={t('project.workspace.panels')}>
          <button type="button" className="project-card" onClick={openInstructions}>
            <span className="project-card__head">
              <span className="project-card__title">{t('project.instructions.title')}</span>
              <span className="project-card__add" aria-hidden>
                <IconPlus size={16} />
              </span>
            </span>
            <p className="project-card__body">
              {savedInstructions ? savedInstructions : t('project.instructions.empty')}
            </p>
          </button>

          <button type="button" className="project-card" onClick={() => setFilesOpen(true)}>
            <span className="project-card__head">
              <span className="project-card__title">{t('project.files.title')}</span>
              <span className="project-card__add" aria-hidden>
                <IconPlus size={16} />
              </span>
            </span>
            <p className="project-card__body">{t('project.files.empty')}</p>
          </button>
        </aside>
      </div>

      <KimiDialog
        open={instructionsOpen}
        title={t('project.instructions.title')}
        closeLabel={t('project.dialog.close')}
        onClose={() => setInstructionsOpen(false)}
        size="md"
        footer={
          <>
            <button
              type="button"
              className="project-dialog__btn project-dialog__btn--ghost"
              onClick={() => setInstructionsOpen(false)}
            >
              {t('project.dialog.cancel')}
            </button>
            <button
              type="button"
              className="project-dialog__btn project-dialog__btn--solid"
              onClick={saveInstructions}
            >
              {t('project.instructions.add')}
            </button>
          </>
        }
      >
        <label className="sr-only" htmlFor={instructionsId}>
          {t('project.instructions.title')}
        </label>
        <textarea
          id={instructionsId}
          className="project-instructions__input"
          value={instructions}
          maxLength={5000}
          placeholder={t('project.instructions.placeholder')}
          rows={8}
          data-autofocus
          onChange={e => setInstructions(e.target.value)}
        />
      </KimiDialog>

      <KimiDialog
        open={filesOpen}
        title={t('project.files.addTitle')}
        closeLabel={t('project.dialog.close')}
        onClose={() => setFilesOpen(false)}
        size="md"
      >
        <p className="project-files__quota">{t('project.files.quota')}</p>
        <button
          type="button"
          className="project-files__zone"
          onClick={() => fileInputRef.current?.click()}
        >
          <IconFileText size={28} aria-hidden />
          <span className="project-files__zone-title">{t('project.files.upload')}</span>
          <span className="project-files__zone-hint">{t('project.files.uploadHint')}</span>
        </button>
        <button
          type="button"
          className="project-files__zone"
          onClick={() => {
            setFilesOpen(false);
            openInstructions();
          }}
        >
          <IconPlus size={28} aria-hidden />
          <span className="project-files__zone-title">{t('project.files.writeText')}</span>
          <span className="project-files__zone-hint">{t('project.files.writeHint')}</span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="sr-only"
          multiple
          onChange={e => {
            if (e.target.files && e.target.files.length > 0) {
              onAddFiles?.(e.target.files);
              setFilesOpen(false);
            }
            e.target.value = '';
          }}
        />
      </KimiDialog>
    </section>
  );
}
