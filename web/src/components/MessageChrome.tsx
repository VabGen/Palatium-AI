import { useState } from 'react';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import { KimiActionIcon } from '../icons/kimiActionIcons';
import { GlyphTask } from '../icons/kimiTokenGlyphs';
import { IconAssistantFace, IconChevronDown } from '../icons/kimiStroke';
import { t } from '../i18n';
import { IconButton } from './ui/IconButton';

export type MessageActionsProps = {
  onCopy: () => void;
  onShare?: () => void;
  onRegenerate?: () => void;
  onLike?: () => void;
  onDislike?: () => void;
  liked?: boolean;
  disliked?: boolean;
  regenerating?: boolean;
  disabled?: boolean;
};

export function MessageActions({
  onCopy,
  onShare,
  onRegenerate,
  onLike,
  onDislike,
  liked,
  disliked,
  regenerating,
  disabled,
}: MessageActionsProps) {
  /*
   * Big Tech 2026: regenerate → copy → share → like → dislike.
   * Thread-level share stays in ZONE_TOP; this shares the answer payload.
   */
  return (
    <div className="msg-actions msg-actions--product" role="group" aria-label={t('action.group')}>
      {onRegenerate ? (
        <IconButton
          size="sm"
          aria-label={t('action.regenerate')}
          title={t('action.regenerate')}
          disabled={disabled || regenerating}
          onClick={onRegenerate}
        >
          <KimiActionIcon name="refresh" size={16} className={regenerating ? 'spin' : undefined} />
        </IconButton>
      ) : null}
      <IconButton
        size="sm"
        aria-label={t('action.copy')}
        title={t('action.copy')}
        disabled={disabled}
        onClick={onCopy}
      >
        <KimiActionIcon name="copy" size={16} />
      </IconButton>
      {onShare ? (
        <IconButton
          size="sm"
          aria-label={t('action.share')}
          title={t('action.share')}
          disabled={disabled}
          onClick={onShare}
        >
          <KimiActionIcon name="share" size={16} />
        </IconButton>
      ) : null}
      {onLike ? (
        <IconButton
          size="sm"
          className={liked ? 'is-active' : undefined}
          aria-label={t('action.like')}
          aria-pressed={liked}
          disabled={disabled}
          onClick={onLike}
        >
          <KimiActionIcon name="like" size={16} />
        </IconButton>
      ) : null}
      {onDislike ? (
        <IconButton
          size="sm"
          className={disliked ? 'is-active' : undefined}
          aria-label={t('action.dislike')}
          aria-pressed={disliked}
          disabled={disabled}
          onClick={onDislike}
        >
          <KimiActionIcon name="dislike" size={16} />
        </IconButton>
      ) : null}
    </div>
  );
}

export type UserMessageActionsProps = {
  onEdit: () => void;
  onCopy: () => void;
  disabled?: boolean;
};

/**
 * kimi.ai ``segment-user-actions``: Edit + Copy (labeled) under the user bubble.
 * Visible on ``.msg.user:hover`` / focus-within — see ``.msg-actions--user``.
 */
export function UserMessageActions({ onEdit, onCopy, disabled }: UserMessageActionsProps) {
  return (
    <div
      className="msg-actions msg-actions--user"
      role="group"
      aria-label={t('action.userGroup')}
    >
      <button
        type="button"
        className="msg-actions__labeled icon-hover"
        disabled={disabled}
        onClick={onEdit}
      >
        <KimiActionIcon name="edit" size={16} />
        <span>{t('action.editLabel')}</span>
      </button>
      <button
        type="button"
        className="msg-actions__labeled icon-hover"
        disabled={disabled}
        onClick={onCopy}
      >
        <KimiActionIcon name="copy" size={16} />
        <span>{t('action.copyLabel')}</span>
      </button>
    </div>
  );
}

export type ThinkingTraceProps = {
  phaseLabel: string;
  detail?: string | null;
  complete?: boolean;
  defaultOpen?: boolean;
};

export function ThinkingTrace({
  phaseLabel,
  detail,
  complete = false,
  defaultOpen = false,
}: ThinkingTraceProps) {
  const [open, setOpen] = useState(defaultOpen);
  const body = detail?.trim() || null;
  // Empty chrome («Размышление завершено» with nothing to expand) is noise — hide it.
  if (!body && complete) return null;
  const title = complete ? t('msg.thinking.done') : phaseLabel;

  return (
    <div className={`thinking-trace${complete ? ' is-done' : ''}`}>
      <button
        type="button"
        className="thinking-trace__toggle icon-hover"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
      >
        <GlyphTask size={14} />
        <span className="thinking-trace__title">{title}</span>
        {body && !complete ? (
          <span className="thinking-trace__sep" aria-hidden>
            |
          </span>
        ) : null}
        {body && !complete ? <span className="thinking-trace__detail">{body}</span> : null}
        <IconChevronDown size={14} className={`thinking-trace__chevron${open ? ' is-open' : ''}`} />
      </button>
      {open && body ? <p className="thinking-trace__body">{body}</p> : null}
    </div>
  );
}

export function AssistantAvatar() {
  return (
    <div className="avatar avatar--assistant" aria-hidden>
      <IconAssistantFace size={28} />
    </div>
  );
}

export type UserAttachmentCardProps = {
  filename: string;
  meta: string;
  /** kimi.ai FileCard: click opens / downloads the file when an id is known. */
  onOpen?: () => void;
  openLabel?: string;
  /** Highlight when this file is open in the right preview rail. */
  active?: boolean;
};

export function UserAttachmentCard({
  filename,
  meta,
  onOpen,
  openLabel,
  active = false,
}: UserAttachmentCardProps) {
  const body = (
    <>
      <span className="user-file-card__icon" aria-hidden>
        <AttachmentFileIcon kind={attachmentFileKind(filename)} size={40} />
      </span>
      <span className="user-file-card__text">
        <span className="user-file-card__name">{filename}</span>
        <span className="user-file-card__meta">{meta}</span>
      </span>
    </>
  );

  const className = `user-file-card${onOpen ? ' user-file-card--interactive' : ''}${
    active ? ' is-active' : ''
  }`;

  if (onOpen) {
    return (
      <button
        type="button"
        className={className}
        onClick={onOpen}
        aria-label={openLabel ?? filename}
        aria-pressed={active}
      >
        {body}
      </button>
    );
  }

  return <div className={className}>{body}</div>;
}
