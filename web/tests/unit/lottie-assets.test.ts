/**
 * Lottie-ассеты статусных иконок — контракт формата кейфреймов.
 *
 * Проверяется не «красиво ли», а единственная причина, по которой иконки были
 * невидимы: `lottie-web` (light) не интерполирует кейфрейм без temporal easing.
 * Такой кейфрейм даёт `NaN` → `matrix(-9999.99, 0, 0, -9999.99, …)` для
 * масштаба и `display: none` для прозрачности, то есть пустую иконку.
 *
 * Legacy-формат с `e` (end value) в 5.x-light тоже не работает — проверено в
 * Chromium; поэтому требуем именно `i`/`o`, а не «какое-нибудь значение».
 */
import { describe, expect, it } from 'vitest';
import dangerAnim from '../../src/lottie/danger.json';
import infoAnim from '../../src/lottie/info.json';
import successAnim from '../../src/lottie/success.json';
import warningAnim from '../../src/lottie/warning.json';

const ASSETS = {
  info: infoAnim,
  success: successAnim,
  warning: warningAnim,
  danger: dangerAnim,
} as const;

type Keyframe = {
  t?: number;
  s?: number[];
  i?: { x: number[]; y: number[] };
  o?: { x: number[]; y: number[] };
};

/** Все анимированные свойства слоя — рекурсивно, включая вложенные группы. */
function animatedProperties(node: unknown, path = '$'): Array<[string, Keyframe[]]> {
  if (node === null || typeof node !== 'object') return [];
  const record = node as Record<string, unknown>;
  const found: Array<[string, Keyframe[]]> = [];

  if (record.a === 1 && Array.isArray(record.k)) {
    found.push([path, record.k as Keyframe[]]);
  }
  for (const [key, value] of Object.entries(record)) {
    if (key === 'k' && record.a === 1) continue;
    found.push(...animatedProperties(value, `${path}.${key}`));
  }
  return found;
}

describe.each(Object.entries(ASSETS))('%s.json', (_name, asset) => {
  it('declares temporal easing on every interpolated keyframe', () => {
    const properties = animatedProperties(asset);
    // Ассет без единой анимации был бы статичной иконкой под именем
    // «анимированной» — это тоже дефект контракта, а не экономия.
    expect(properties.length).toBeGreaterThan(0);

    for (const [path, keyframes] of properties) {
      expect(keyframes.length, `${path}: минимум два кейфрейма`).toBeGreaterThan(1);
      // Последний кейфрейм — только точка остановки: easing ему не нужен.
      for (const keyframe of keyframes.slice(0, -1)) {
        expect(keyframe.i, `${path}@t=${keyframe.t}: нет i (easing)`).toBeDefined();
        expect(keyframe.o, `${path}@t=${keyframe.t}: нет o (easing)`).toBeDefined();
        expect(keyframe.i?.x.length, `${path}@t=${keyframe.t}: i.x`).toBeGreaterThan(0);
        expect(keyframe.i?.y.length, `${path}@t=${keyframe.t}: i.y`).toBeGreaterThan(0);
      }
      const last = keyframes.at(-1);
      expect(last?.s, `${path}: последний кейфрейм без значения`).toBeDefined();
    }
  });

  it('keeps a sane timeline and viewport', () => {
    expect(asset.fr).toBeGreaterThan(0);
    expect(asset.op).toBeGreaterThan(asset.ip);
    expect(asset.w).toBeGreaterThan(0);
    expect(asset.h).toBeGreaterThan(0);
    expect(asset.layers.length).toBeGreaterThan(0);
  });
});

describe('keyframe values stay inside the painted viewport', () => {
  /**
   * `scale` в Lottie — проценты. Значение порядка десятков тысяч (как
   * `-9999.99` из NaN) вырождает слой; здесь закреплён осмысленный диапазон,
   * чтобы «починенный» ассет не оказался невидимым по другой причине.
   */
  it.each(Object.entries(ASSETS))('%s', (_name, asset) => {
    for (const [, keyframes] of animatedProperties(asset)) {
      for (const keyframe of keyframes) {
        for (const value of keyframe.s ?? []) {
          expect(Number.isFinite(value)).toBe(true);
          expect(Math.abs(value)).toBeLessThan(1000);
        }
      }
    }
  });
});
