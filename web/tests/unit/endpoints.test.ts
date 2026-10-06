import { describe, expect, it } from 'vitest';

import { ASSISTANT_API_PATH, ASSISTANT_WS_PATH } from '@palatium/contract';

import {
  resolveApiBase,
  resolveApiUrl,
  resolveSessionSocketUrl,
} from '../../src/runtime/endpoints';

const ORIGIN = 'https://edo.example';

describe('REST base', () => {
  it('falls back to the contract path when the build defines no base', () => {
    expect(resolveApiBase('')).toBe(ASSISTANT_API_PATH);
    expect(resolveApiBase('   ')).toBe(ASSISTANT_API_PATH);
  });

  it('strips trailing slashes so a double slash never reaches the proxy', () => {
    expect(resolveApiBase('https://palatium.example/api/')).toBe('https://palatium.example/api');
    expect(resolveApiUrl('https://palatium.example/api//', '/intents/process')).toBe(
      'https://palatium.example/api/intents/process'
    );
  });

  it('joins a relative path onto a relative base', () => {
    expect(resolveApiUrl('', '/intents/process')).toBe('/api/intents/process');
  });

  it('keeps an absolute URL untouched — presigned store URLs are not ours to rewrite', () => {
    const presigned = 'http://127.0.0.1:9000/bucket/key?X-Amz-Signature=abc';
    expect(resolveApiUrl('/api', presigned)).toBe(presigned);
  });
});

describe('session socket address', () => {
  it('stays on the page origin for a relative base, so no CORS/allowlist is needed', () => {
    const url = resolveSessionSocketUrl('', ORIGIN, 'th-1', 'tok');

    expect(url).toBe(`wss://edo.example${ASSISTANT_WS_PATH}/th-1?token=tok`);
  });

  it('takes scheme and host from an absolute base — https must become wss, not ws', () => {
    const url = resolveSessionSocketUrl('https://palatium.example/api', ORIGIN, 'th-1', 'tok');

    // `ws://` from an HTTPS page is mixed content: the browser blocks it before it
    // reaches the server, so the scheme has to follow the API base, not the page.
    expect(url).toBe(`wss://palatium.example${ASSISTANT_WS_PATH}/th-1?token=tok`);
  });

  it('keeps a path prefix that sits in front of /api (reverse proxy under a subpath)', () => {
    const url = resolveSessionSocketUrl('/sed/api', ORIGIN, 'th-1', 'tok');

    expect(url).toBe(`wss://edo.example/sed${ASSISTANT_WS_PATH}/th-1?token=tok`);
  });

  it('derives the socket from the SAME base as REST (W9: one source of addresses)', () => {
    const base = 'https://palatium.example/prefix/api';
    const rest = new URL(resolveApiUrl(base, '/intents/process'));
    const socket = new URL(resolveSessionSocketUrl(base, ORIGIN, 'th-1', 'tok'));

    // Host совпадает, а `/api` в общем префиксе заменяется на `/ws/sessions`: одна
    // база, две схемы. Разъехавшиеся адреса — ровно тот баг, ради которого W9 завёл
    // единственную точку вычисления.
    expect(socket.host).toBe(rest.host);
    expect(socket.protocol).toBe('wss:');
    expect(socket.pathname).toBe('/prefix/ws/sessions/th-1');
    expect(rest.pathname).toBe('/prefix/api/intents/process');
  });

  it('encodes thread id and token, so a token with & or a space cannot forge a query param', () => {
    const url = resolveSessionSocketUrl('', ORIGIN, 'th 1/2', 'a b&c=d');

    expect(url).toContain('/th%201%2F2?token=a%20b%26c%3Dd');
  });
});
