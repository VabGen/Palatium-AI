export type SessionSocketMessage =
  | { type: 'session.subscribed'; thread_id: string; trace_id: string }
  | { type: 'pong'; trace_id?: string }
  | { type: 'error'; detail?: string };

export type SessionSocketHandlers = {
  onSubscribed?: (payload: SessionSocketMessage & { type: 'session.subscribed' }) => void;
  onPong?: () => void;
  onError?: (detail: string) => void;
};

export function connectSessionSocket(
  threadId: string,
  token: string,
  handlers: SessionSocketHandlers
): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(
    `${proto}//${window.location.host}/ws/sessions/${encodeURIComponent(threadId)}?token=${encodeURIComponent(token)}`
  );

  ws.onmessage = event => {
    try {
      const data = JSON.parse(String(event.data)) as SessionSocketMessage;
      if (data.type === 'session.subscribed') {
        handlers.onSubscribed?.(data);
      } else if (data.type === 'pong') {
        handlers.onPong?.();
      } else if (data.type === 'error') {
        handlers.onError?.(data.detail ?? 'websocket_error');
      }
    } catch {
      handlers.onError?.('invalid_websocket_payload');
    }
  };

  ws.onerror = () => {
    handlers.onError?.('websocket_connection_error');
  };

  return ws;
}

export function startSessionSocketPing(socket: WebSocket, intervalMs = 30_000): () => void {
  const timer = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send('ping');
    }
  }, intervalMs);
  return () => window.clearInterval(timer);
}
