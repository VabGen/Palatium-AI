import { describe, expect, it } from 'vitest';

import { resolveMimeType } from '../../src/lib/attachments';

function file(name: string, type: string): File {
  return new File(['x'], name, { type });
}

/**
 * `File.type` приходит из чужой страницы, поэтому `resolveMimeType` — граница
 * доверия, а не удобный хелпер: ошибка здесь всплывает как исключение прямо в
 * обработчике выбора файла, то есть ломает отправку вложения без сообщения.
 */
describe('resolveMimeType', () => {
  it('keeps the declared type when it agrees with the extension', () => {
    expect(resolveMimeType(file('scan.pdf', 'application/pdf'))).toBe('application/pdf');
    expect(resolveMimeType(file('photo.JPG', 'image/jpeg'))).toBe('image/jpeg');
  });

  it('refuses a mismatch instead of sending a doomed request', () => {
    expect(resolveMimeType(file('scan.pdf', 'image/png'))).toBeNull();
  });

  it('falls back to the extension when the browser declares nothing', () => {
    expect(resolveMimeType(file('notes.md', ''))).toBe('text/markdown');
    expect(resolveMimeType(file('data.csv', ''))).toBe('text/csv');
  });

  it('rejects an extension outside the registry', () => {
    expect(resolveMimeType(file('payload.exe', ''))).toBeNull();
    expect(resolveMimeType(file('payload.exe', 'application/octet-stream'))).toBeNull();
  });

  /**
   * Regression: `MEDIA_EXTENSIONS[declared]` шёл по цепочке прототипов, и
   * `type="constructor"` возвращал `Object` — truthy, после чего `.includes`
   * бросал `TypeError` и отправка файла падала.
   */
  it.each(['constructor', '__proto__', 'toString', 'valueOf', 'hasOwnProperty'])(
    'does not throw for the inherited property %s',
    hostile => {
      expect(() => resolveMimeType(file('scan.pdf', hostile))).not.toThrow();
      // Registry не совпал — остаётся путь по расширению, то есть `application/pdf`.
      expect(resolveMimeType(file('scan.pdf', hostile))).toBe('application/pdf');
    }
  );
});
