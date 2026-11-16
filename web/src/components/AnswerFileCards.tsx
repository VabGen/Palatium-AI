/**
 * kimi.ai under-answer file pills: primary file/artifact + «Все файлы».
 * Color System neutrals + Brand accent only on active state.
 */
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import { IconFolder } from '../icons/kimiStroke';
import { t } from '../i18n';
import { attachmentDisplayName, attachmentTypeLabel } from '../lib/attachments';

export type AnswerFileCardsProps = {
  /** Document title when opening the answer as an artifact pane. */
  artifactTitle?: string | null;
  artifactActive?: boolean;
  onOpenArtifact?: () => void;
  /** First cited/source attachment — preferred primary card when present. */
  primaryFile?: { id: string; filename: string } | null;
  primaryActive?: boolean;
  onOpenPrimary?: (id: string, filename: string) => void;
  showAllFiles: boolean;
  allFilesActive?: boolean;
  onOpenAllFiles: () => void;
};

export function AnswerFileCards({
  artifactTitle,
  artifactActive = false,
  onOpenArtifact,
  primaryFile = null,
  primaryActive = false,
  onOpenPrimary,
  showAllFiles,
  allFilesActive = false,
  onOpenAllFiles,
}: AnswerFileCardsProps) {
  /* kimi.ai: «Ответ» artifact + primary file + «Все файлы» can coexist */
  const showArtifact = Boolean(onOpenArtifact);
  if (!showArtifact && !primaryFile && !showAllFiles) return null;

  return (
    <div className="answer-file-cards" role="group" aria-label={t('attach.allFiles')}>
      {showArtifact && onOpenArtifact ? (
        <button
          type="button"
          className={`answer-file-card${artifactActive ? ' is-active' : ''}`}
          onClick={onOpenArtifact}
          aria-label={t('artifact.open')}
        >
          <span className="answer-file-card__icon" aria-hidden>
            <AttachmentFileIcon kind="generic" size={40} />
          </span>
          <span className="answer-file-card__text">
            <span className="answer-file-card__title">
              {artifactTitle?.trim() || t('artifact.untitled')}
            </span>
            <span className="answer-file-card__meta">{t('artifact.kicker')}</span>
          </span>
          <span className="answer-file-card__preview">{t('artifact.preview')}</span>
        </button>
      ) : null}

      {primaryFile && onOpenPrimary ? (
        <button
          type="button"
          className={`answer-file-card${primaryActive ? ' is-active' : ''}`}
          onClick={() => onOpenPrimary(primaryFile.id, primaryFile.filename)}
          aria-label={t('attach.openFile', { name: primaryFile.filename })}
        >
          <span className="answer-file-card__icon" aria-hidden>
            <AttachmentFileIcon kind={attachmentFileKind(primaryFile.filename)} size={40} />
          </span>
          <span className="answer-file-card__text">
            <span className="answer-file-card__title">
              {attachmentDisplayName(primaryFile.filename)}
            </span>
            <span className="answer-file-card__meta">
              {attachmentTypeLabel(primaryFile.filename) || t('artifact.kicker')}
            </span>
          </span>
          <span className="answer-file-card__preview">{t('artifact.preview')}</span>
        </button>
      ) : null}

      {showAllFiles ? (
        <button
          type="button"
          className={`answer-file-card${allFilesActive ? ' is-active' : ''}`}
          onClick={onOpenAllFiles}
          aria-label={t('attach.allFiles')}
        >
          <span className="answer-file-card__icon answer-file-card__icon--folder" aria-hidden>
            <IconFolder size={22} />
          </span>
          <span className="answer-file-card__text">
            <span className="answer-file-card__title">{t('attach.allFiles')}</span>
            <span className="answer-file-card__meta">{t('attach.allFilesDesc')}</span>
          </span>
          <span className="answer-file-card__preview">{t('artifact.preview')}</span>
        </button>
      ) : null}
    </div>
  );
}
