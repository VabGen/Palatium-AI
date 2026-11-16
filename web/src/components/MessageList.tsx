import { forwardRef, type ReactNode } from 'react';
import { Avatar, type AvatarKind } from './ui/Avatar';

export type MessageListProps = {
  label: string;
  children: ReactNode;
  empty?: ReactNode;
};

/**
 * [ZONE_BODY] лента сообщений.
 * Data Visualization: нейтральный canvas; акцент только на данных/CTA через токены.
 * ``ref`` — scroll root для DialogueNav (IntersectionObserver + jump).
 */
export const MessageList = forwardRef<HTMLDivElement, MessageListProps>(function MessageList(
  { label, children, empty },
  ref
) {
  return (
    <div
      ref={ref}
      className="transcript message-list"
      part="transcript"
      role="log"
      aria-live="off"
      aria-label={label}
    >
      {empty}
      {children}
    </div>
  );
});

export type MessageRowProps = {
  role: 'user' | 'assistant';
  children: ReactNode;
  waiting?: boolean;
  className?: string;
  showAvatar?: boolean;
  avatarKind?: AvatarKind;
};

/**
 * Строка сообщения. Фоны — `--msg-*-bg` из Color System; без сырого hex.
 */
export function MessageRow({
  role,
  children,
  waiting = false,
  className,
  showAvatar = false,
  avatarKind,
}: MessageRowProps) {
  const kind = avatarKind ?? (role === 'user' ? 'user' : waiting ? 'thinking' : 'assistant');
  const classes = ['msg', 'message-row', role, waiting ? 'is-waiting' : null, className]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes}>
      {showAvatar ? (
        <div className="message-row__avatar">
          {kind === 'thinking' ? (
            <Avatar kind="thinking" size={40} />
          ) : (
            <Avatar kind={kind} size={28} />
          )}
        </div>
      ) : (
        <div className="avatar" aria-hidden="true">
          {role === 'user' ? 'U' : 'P'}
        </div>
      )}
      <div className="bubble message-row__bubble">{children}</div>
    </div>
  );
}
