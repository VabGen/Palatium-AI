import { describe, expect, it } from 'vitest';

import {
  buildDepartmentScope,
  checkTenantConsistency,
  isAssistantAction,
  isSedContext,
  normalizeThreadId,
  preferredName,
  THREAD_ID_MAX_LENGTH,
  toBcp47,
  type SedContext,
} from '@palatium/contract';

/**
 * Границы доверия контракта (084).
 *
 * Контекст приходит `CustomEvent`'ом со страницы host, где писать может кто угодно,
 * поэтому эти функции — не «утилиты», а единственный барьер между чужой страницей и
 * состоянием виджета. Проверяем НЕ happy path (его видно в E2E), а отказы: мусорный
 * payload обязан быть отброшен на границе (035: fail-closed), а не уронить рендер.
 */

/** Payload JWT без подписи: виджет читает claims только для сверки, не для прав. */
function tokenWith(claims: Record<string, unknown>): string {
  const base64url = btoa(JSON.stringify(claims))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `header.${base64url}.signature`;
}

function validContext(overrides: Partial<SedContext> = {}): SedContext {
  return {
    token: tokenWith({ org_id: 'org-1' }),
    user: { id: 'u-1', orgId: 'org-1' },
    scope: { tenantId: 'org-1', departmentIds: [] },
    ...overrides,
  };
}

describe('isSedContext', () => {
  it('accepts a minimal consistent context', () => {
    expect(isSedContext(validContext())).toBe(true);
  });

  it.each([
    ['null', null],
    ['a primitive', 'sed:context-changed'],
    ['an array', []],
    ['an empty object', {}],
  ])('rejects %s', (_label, value) => {
    expect(isSedContext(value)).toBe(false);
  });

  it.each([
    ['a blank token', { token: '   ' }],
    ['a missing user', { user: undefined }],
    ['a blank user id', { user: { id: '', orgId: 'org-1' } }],
    ['a blank org id', { user: { id: 'u-1', orgId: '' } }],
    ['a missing scope', { scope: undefined }],
    ['a blank tenant', { scope: { tenantId: '  ', departmentIds: [] } }],
    ['a non-array department scope', { scope: { tenantId: 'org-1', departmentIds: 'd-1' } }],
  ])('rejects %s', (_label, patch) => {
    expect(isSedContext({ ...validContext(), ...patch })).toBe(false);
  });
});

describe('normalizeThreadId', () => {
  it('trims a value the host may have padded', () => {
    expect(normalizeThreadId('  th-1  ')).toBe('th-1');
  });

  it('accepts exactly the server limit and rejects one character more', () => {
    const atLimit = 'a'.repeat(THREAD_ID_MAX_LENGTH);

    expect(normalizeThreadId(atLimit)).toBe(atLimit);
    expect(normalizeThreadId(`${atLimit}a`)).toBeNull();
  });

  it.each([
    ['a non-string', 42],
    ['an empty string', ''],
    ['only whitespace', '   '],
  ])('returns null for %s instead of throwing', (_label, value) => {
    // Мусор в ОДНОМ поле не должен стоить всего контекста (токен, локаль, права):
    // поэтому здесь `null`, а не исключение.
    expect(normalizeThreadId(value)).toBeNull();
  });
});

describe('checkTenantConsistency', () => {
  it('is ok when user, scope and token claim agree', () => {
    expect(checkTenantConsistency(validContext())).toBe('ok');
  });

  it('ignores case: orgId in SED is a string id, not a UUID', () => {
    const context = validContext({
      user: { id: 'u-1', orgId: 'ORG-1' },
      scope: { tenantId: 'org-1', departmentIds: [] },
    });

    expect(checkTenantConsistency(context)).toBe('ok');
  });

  it('is unknown when the token carries no tenant claim (dev token)', () => {
    const context = validContext({ token: tokenWith({ sub: 'u-1' }) });

    expect(checkTenantConsistency(context)).toBe('unknown');
  });

  it('is mismatch when the user org contradicts the scope tenant', () => {
    const context = validContext({
      user: { id: 'u-1', orgId: 'org-2' },
      scope: { tenantId: 'org-1', departmentIds: [] },
    });

    expect(checkTenantConsistency(context)).toBe('mismatch');
  });

  it('is mismatch when the token claim belongs to another tenant', () => {
    const context = validContext({ token: tokenWith({ org: 'org-2' }) });

    expect(checkTenantConsistency(context)).toBe('mismatch');
  });
});

describe('isAssistantAction', () => {
  it('rejects a view outside the closed list — the host owns its routes', () => {
    expect(isAssistantAction({ action: 'navigate', view: 'admin' })).toBe(false);
    expect(isAssistantAction({ action: 'navigate', view: '/admin/users' })).toBe(false);
  });

  it('accepts only the closed set of view keys', () => {
    for (const view of ['home', 'my_documents', 'my_tasks']) {
      expect(isAssistantAction({ action: 'navigate', view })).toBe(true);
    }
  });

  it.each([
    ['an unknown action', { action: 'delete_document', documentId: 'd-1' }],
    ['a missing document id', { action: 'open_document' }],
    ['a blank document id', { action: 'open_document', documentId: '   ' }],
    ['a blank search query', { action: 'search', query: '  ' }],
    ['a raw dict without an action', { payload: { action: 'navigate' } }],
    ['null', null],
  ])('rejects %s', (_label, value) => {
    expect(isAssistantAction(value)).toBe(false);
  });

  it('accepts well-formed open_document and search actions', () => {
    expect(isAssistantAction({ action: 'open_document', documentId: 'd-1' })).toBe(true);
    expect(isAssistantAction({ action: 'search', query: 'договор' })).toBe(true);
  });
});

describe('toBcp47', () => {
  it('maps the localizations that have resources', () => {
    expect(toBcp47('RU')).toBe('ru-RU');
    expect(toBcp47('EN')).toBe('en-US');
  });

  it('returns null for GE — SED has no resources for it, so it is not a locale we may name', () => {
    expect(toBcp47('GE')).toBeNull();
    expect(toBcp47(undefined)).toBeNull();
  });
});

describe('preferredName', () => {
  it('prefers the explicit firstName', () => {
    expect(preferredName({ id: 'u-1', orgId: 'org-1', firstName: ' Иван ' })).toBe('Иван');
  });

  it('falls back to fullName as-is — the order inside it is not part of the contract', () => {
    // Разбор «Фамилия Имя» по позиции обратился бы к человеку по фамилии (090).
    expect(preferredName({ id: 'u-1', orgId: 'org-1', fullName: 'Иванов Иван' })).toBe(
      'Иванов Иван'
    );
  });

  it('returns null when there is nothing to address the user by', () => {
    expect(preferredName(undefined)).toBeNull();
    expect(preferredName({ id: 'u-1', orgId: 'org-1', fullName: '   ' })).toBeNull();
  });
});

describe('buildDepartmentScope', () => {
  it('unions the department id with subordinates and responsible ones without duplicates', () => {
    expect(
      buildDepartmentScope('d-1', {
        authorities: [],
        roles: [],
        subordinatesDepartments: ['d-2', 'd-1'],
        responsibleNomenclatureDepartmentIds: ['d-3', 'd-2'],
      })
    ).toEqual(['d-1', 'd-2', 'd-3']);
  });

  it('returns an empty scope when permissions are absent', () => {
    expect(buildDepartmentScope(undefined, undefined)).toEqual([]);
  });
});
