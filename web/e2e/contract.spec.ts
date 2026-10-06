/**
 * Контракт `@palatium/contract` (W9) — то, что не видно в UI, но ломает интеграцию.
 *
 * Два инварианта, которые нельзя проверить пикселем:
 * 1) согласованность tenant'а в контексте host'а (`checkTenantConsistency`) —
 *    расхождение даёт тихую путаницу данных между организациями, а не ошибку;
 * 2) закрытый каталог действий `sed:action-requested` (`isAssistantAction`) —
 *    СЭД разбирает detail только через него, и произвольная строка в `action`
 *    не должна проходить как «валидное действие».
 *
 * Функции чистые, но живут в браузерном бандле, поэтому вызываются в странице:
 * `page.evaluate` не сериализует функции наружу (см. `endpoints.spec.ts`).
 */
import { expect, test, type Page } from '@playwright/test';
import { sedJwt } from './fixtures';

/**
 * Набор токенов для обоих тестов.
 *
 * Один и тот же: проверка действий тоже прогоняет контекст (валидация действия
 * живёт рядом с валидацией контекста), и токен без claims уронил бы разбор.
 */
function sampleTokens(): Record<string, string> {
  return {
    matching: sedJwt({ sub: 'u-1', org_id: '114' }),
    other: sedJwt({ sub: 'u-1', org_id: '777' }),
    plain: 'e2e-token',
    upper: sedJwt({ sub: 'u-1', org_id: ' 114 ' }),
    orgClaim: sedJwt({ sub: 'u-1', org: '114' }),
  };
}

interface ContractProbe {
  readonly consistency: Readonly<Record<string, string>>;
  readonly tenantClaim: Readonly<Record<string, string | null>>;
  readonly acceptedActions: readonly string[];
  readonly rejectedActions: readonly unknown[];
  readonly names: Readonly<Record<string, string | null>>;
  readonly threads: Readonly<Record<string, string | null>>;
}

async function probeContract(page: Page, tokens: Record<string, string>): Promise<ContractProbe> {
  return page.evaluate(
    async input => {
      const specifier = '/packages/contract/src/index.ts';
      const m = (await import(/* @vite-ignore */ specifier)) as {
        checkTenantConsistency: (context: unknown) => string;
        tokenTenantId: (token: string) => string | null;
        isAssistantAction: (value: unknown) => boolean;
        preferredName: (user: unknown) => string | null;
        normalizeThreadId: (value: unknown) => string | null;
        THREAD_ID_MAX_LENGTH: number;
      };

      const context = (overrides: Record<string, unknown>): unknown => ({
        token: input.tokens.matching,
        user: { id: 'u-1', orgId: '114' },
        scope: { tenantId: '114', departmentIds: [] },
        ...overrides,
      });

      const actions: readonly unknown[] = [
        { action: 'open_document', documentId: 'doc-1' },
        { action: 'navigate', view: 'my_tasks' },
        { action: 'search', query: 'договор 42' },
      ];

      return {
        consistency: {
          ok: m.checkTenantConsistency(context({})),
          otherToken: m.checkTenantConsistency(context({ token: input.tokens.other })),
          userOrgInconsistent: m.checkTenantConsistency(
            context({ user: { id: 'u-1', orgId: '999' } })
          ),
          scopeInconsistent: m.checkTenantConsistency(
            context({ scope: { tenantId: '999', departmentIds: [] } })
          ),
          noClaim: m.checkTenantConsistency(context({ token: input.tokens.plain })),
          casing: m.checkTenantConsistency(context({ token: input.tokens.upper })),
          orgFallback: m.checkTenantConsistency(context({ token: input.tokens.orgClaim })),
          malformed: m.checkTenantConsistency(context({ token: 'not-a-jwt' })),
        },
        tenantClaim: {
          orgId: m.tokenTenantId(input.tokens.matching),
          org: m.tokenTenantId(input.tokens.orgClaim),
          plain: m.tokenTenantId(input.tokens.plain),
          malformed: m.tokenTenantId('not-a-jwt'),
        },
        acceptedActions: actions
          .filter(action => m.isAssistantAction(action))
          .map(action => (action as { action: string }).action),
        rejectedActions: [
          undefined,
          null,
          'open_document',
          { action: 'open_document' },
          { action: 'open_document', documentId: '   ' },
          { action: 'navigate' },
          { action: 'navigate', view: 'admin_panel' },
          { action: 'navigate', view: '/document/incoming' },
          { action: 'search', query: '  ' },
          { action: 'delete_document', documentId: 'doc-1' },
        ].filter(value => m.isAssistantAction(value)),
        names: {
          firstName: m.preferredName({
            id: 'u-1',
            orgId: '114',
            firstName: 'Иван',
            fullName: 'Петров Иван',
          }),
          firstNamePadded: m.preferredName({ id: 'u-1', orgId: '114', firstName: '  Иван ' }),
          // `firstName` пуст → берём `fullName` КАК ЕСТЬ: порядок слов в СЭД не зафиксирован.
          fullNameOnly: m.preferredName({ id: 'u-1', orgId: '114', fullName: 'Петров Иван' }),
          blankFirstName: m.preferredName({
            id: 'u-1',
            orgId: '114',
            firstName: '   ',
            fullName: 'Петров Иван',
          }),
          absent: m.preferredName({ id: 'u-1', orgId: '114' }),
          noUser: m.preferredName(undefined),
        },
        threads: {
          plain: m.normalizeThreadId('thread-abc'),
          // Пробелы — форматирование, а не часть id: сервер хранит значение как есть,
          // поэтому нормализация делается на границе, а не в запросе.
          padded: m.normalizeThreadId('  thread-abc  '),
          empty: m.normalizeThreadId(''),
          blank: m.normalizeThreadId('   '),
          notString: m.normalizeThreadId(42),
          missing: m.normalizeThreadId(undefined),
          // Ровно лимит сервера (`thread_id`: 1…128) проходит, на байт больше — нет.
          atLimit: m.normalizeThreadId('t'.repeat(m.THREAD_ID_MAX_LENGTH)),
          overLimit: m.normalizeThreadId('t'.repeat(m.THREAD_ID_MAX_LENGTH + 1)),
        },
      };
    },
    { tokens }
  );
}

test.describe('контракт внедрения', () => {
  test('tenant сверяется по токену, user.orgId и scope.tenantId', async ({ page }) => {
    await page.goto('/standalone.html');
    const probe = await probeContract(page, sampleTokens());

    expect(probe.consistency.ok).toBe('ok');
    // Токен чужой организации: сервер обслуживает его tenant, хост думает — свой.
    expect(probe.consistency.otherToken).toBe('mismatch');
    expect(probe.consistency.userOrgInconsistent).toBe('mismatch');
    expect(probe.consistency.scopeInconsistent).toBe('mismatch');
    // Пробелы/регистр — не часть значения orgId, а форматирование.
    expect(probe.consistency.casing).toBe('ok');
    // `org` — второй claim, который читает бэкенд (`presentation/security/jwt.py`).
    expect(probe.consistency.orgFallback).toBe('ok');
    // Токен без tenant-claim и не-JWT — «неизвестно», а не расхождение.
    expect(probe.consistency.noClaim).toBe('unknown');
    expect(probe.consistency.malformed).toBe('unknown');
    expect(probe.tenantClaim).toEqual({ orgId: '114', org: '114', plain: null, malformed: null });
  });

  test('каталог действий закрыт: незнакомое действие не проходит валидацию', async ({ page }) => {
    await page.goto('/standalone.html');
    const probe = await probeContract(page, sampleTokens());

    expect(probe.acceptedActions).toEqual(['open_document', 'navigate', 'search']);
    // Ни мусор, ни «сырой dict», ни путь вместо ключа раздела, ни действие,
    // которого нет в каталоге: host обязан получить отказ, а не выполнить.
    expect(probe.rejectedActions).toEqual([]);
  });

  test('имя для обращения: firstName приоритетен, fullName — без разбора по позиции', async ({
    page,
  }) => {
    await page.goto('/standalone.html');
    const probe = await probeContract(page, sampleTokens());

    expect(probe.names).toEqual({
      firstName: 'Иван',
      firstNamePadded: 'Иван',
      // Порядок слов полноты не угадываем: «Фамилия Имя» и «Имя Фамилия» дали бы
      // обращение то по фамилии, то по имени — host присылает готовую форму.
      fullNameOnly: 'Петров Иван',
      blankFirstName: 'Петров Иван',
      // Не по чему обращаться — шаблон без имени, а не «Здравствуйте, ».
      absent: null,
      noUser: null,
    });
  });

  test('тред проверяется на границе теми же лимитами, что у сервера', async ({ page }) => {
    await page.goto('/standalone.html');
    const probe = await probeContract(page, sampleTokens());

    const atLimit = 't'.repeat(128);
    expect(probe.threads).toEqual({
      plain: 'thread-abc',
      padded: 'thread-abc',
      // `null` — «не тред» и это НЕ ошибка контекста: остальные поля (токен,
      // локаль, права) остаются валидными, виджет просто продолжит с новым тредом.
      empty: null,
      blank: null,
      notString: null,
      missing: null,
      atLimit,
      // Лимит взят из того же места, что и объявлен: `128` в тесте и `128` в
      // правиле — одно число, иначе проверка защищала бы только себя (050).
      overLimit: null,
    });
  });
});
