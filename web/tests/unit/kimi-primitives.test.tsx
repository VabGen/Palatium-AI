import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MessageActions, UserMessageActions } from '../../src/components/MessageChrome';
import { MessageList, MessageRow } from '../../src/components/MessageList';
import { TopBar } from '../../src/components/TopBar';
import { Avatar, Button, Input } from '../../src/components/ui';
import { t } from '../../src/i18n';

describe('Kimi Color System tokens', () => {
  it('exposes wash / popover / code semantics used by styles.css', () => {
    const tokensPath = path.join(
      path.dirname(fileURLToPath(import.meta.url)),
      '../../src/tokens.css'
    );
    const text = readFileSync(tokensPath, 'utf8');
    expect(text).toContain('--wash-white-6');
    expect(text).toContain('--bg-popover');
    expect(text).toContain('--bg-code');
    expect(text).toContain('--kimi-danger-deep');
    expect(text).toContain('--accent-hover');
    expect(text).toContain('--kimi-surface-elevated');
    expect(text).toContain('--kimi-border');
  });
});

describe('Kimi primitives', () => {
  it('renders Logo System mark for assistant avatar', () => {
    const { container } = render(<Avatar kind="assistant" size={28} />);
    expect(container.querySelector('.kimi-avatar__mark')).not.toBeNull();
  });

  it('uses thinking-orbs canvas for loading avatar', () => {
    const { container } = render(<Avatar kind="thinking" size={40} />);
    expect(container.querySelector('canvas')).not.toBeNull();
  });

  it('exposes button variants without raw hex', () => {
    render(
      <Button variant="primary" onClick={() => undefined}>
        Send
      </Button>
    );
    expect(screen.getByRole('button', { name: 'Send' })).toHaveClass('kimi-btn--primary');
  });

  it('renders input with kimi class', () => {
    render(<Input aria-label="query" />);
    expect(screen.getByLabelText('query')).toHaveClass('kimi-input');
  });
});

describe('TopBar / MessageList zones', () => {
  it('marks ZONE_TOP on the top bar', () => {
    const { container } = render(
      <TopBar
        title="Palatium"
        newChatLabel="New"
        collapseLabel="Collapse"
        onNewChat={() => undefined}
        onCollapse={() => undefined}
      />
    );
    expect(container.querySelector('[data-zone="ZONE_TOP"]')).not.toBeNull();
  });

  it('keeps transcript as a quiet log region', () => {
    render(
      <MessageList label="Transcript">
        <MessageRow role="user">Hello</MessageRow>
      </MessageList>
    );
    const log = screen.getByRole('log', { name: 'Transcript' });
    expect(log).toHaveAttribute('aria-live', 'off');
    expect(log).toHaveClass('message-list');
  });

  it('wires active-chat share and skips the stub more control', () => {
    const onShare = vi.fn();
    render(
      <TopBar
        title="Palatium"
        threadTitle="Keyboard Layout"
        hasMessages
        newChatLabel="New chat"
        collapseLabel="Collapse"
        onNewChat={() => undefined}
        onShareThread={onShare}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: t('thread.share') }));
    expect(onShare).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: t('thread.more') })).toBeNull();
  });

  it('orders message actions regenerate → copy → feedback', () => {
    const { container } = render(
      <MessageActions
        onCopy={() => undefined}
        onRegenerate={() => undefined}
        onLike={() => undefined}
        onDislike={() => undefined}
      />
    );
    const labels = [...container.querySelectorAll('.msg-actions--product .icon-btn')].map(btn =>
      btn.getAttribute('aria-label')
    );
    expect(labels).toEqual([
      t('action.regenerate'),
      t('action.copy'),
      t('action.like'),
      t('action.dislike'),
    ]);
  });

  it('exposes user message Edit + Copy labels', () => {
    const onEdit = vi.fn();
    const onCopy = vi.fn();
    render(<UserMessageActions onEdit={onEdit} onCopy={onCopy} />);
    fireEvent.click(screen.getByRole('button', { name: t('action.editLabel') }));
    fireEvent.click(screen.getByRole('button', { name: t('action.copyLabel') }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onCopy).toHaveBeenCalledTimes(1);
  });
});
