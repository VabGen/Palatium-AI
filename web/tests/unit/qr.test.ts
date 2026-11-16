import { describe, expect, it } from 'vitest';
import QRCode from 'qrcode';

import { encodeQr, qrToSvg } from '../../src/lib/qr';

/**
 * Эталон — независимая реализация (`qrcode`, devDependency). Сравниваем каждую
 * моду на всех восьми масках: расхождение хотя бы в одном модуле означает, что
 * QR не сканируется, а глазами это не видно.
 *
 * Маску навязываем обеим реализациям: эвристика штрафа (N4) в библиотеке
 * округляет иначе, чем ISO 18004, поэтому «лучшая» маска может отличаться —
 * на корректность символа это не влияет, на сравнение матриц влияло бы.
 */
const SAMPLES = [
  'http://127.0.0.1:5174/ui/',
  'https://palatium.example/app',
  'Привет',
  'Palatium',
  'a'.repeat(120),
];

const MASKS = [0, 1, 2, 3, 4, 5, 6, 7] as const;
type Mask = (typeof MASKS)[number];

interface ReferenceMatrix {
  size: number;
  get(row: number, col: number): number;
}

function reference(text: string, maskPattern: Mask): ReferenceMatrix {
  // Явный byte-сегмент: иначе библиотека оптимизирует URL/цифры в numeric или
  // alphanumeric сегменты, и матрицы расходятся не из-за ошибки энкодера.
  const code = QRCode.create([{ data: new TextEncoder().encode(text), mode: 'byte' }], {
    errorCorrectionLevel: 'M',
    maskPattern,
  });
  return code.modules as unknown as ReferenceMatrix;
}

function assertSameMatrix(mine: readonly (readonly boolean[])[], expected: ReferenceMatrix): void {
  expect(mine.length).toBe(expected.size);
  for (let y = 0; y < expected.size; y += 1) {
    expect(mine[y].length).toBe(expected.size);
    for (let x = 0; x < expected.size; x += 1) {
      expect(mine[y][x], `модуль (${x},${y})`).toBe(expected.get(y, x) === 1);
    }
  }
}

describe('encodeQr', () => {
  it.each(SAMPLES)('совпадает с эталоном на всех масках: %s', text => {
    for (const mask of MASKS) {
      const mine = encodeQr(text, 'M', mask);
      expect(mine.mask).toBe(mask);
      assertSameMatrix(mine.modules, reference(text, mask));
    }
  });

  it.each(SAMPLES)('автоматическая маска даёт валидный символ: %s', text => {
    const mine = encodeQr(text, 'M');
    const library = reference(text, mine.mask as Mask);
    assertSameMatrix(mine.modules, library);
  });

  it('рендерит SVG с одним путём и нужным размером', () => {
    const svg = qrToSvg(encodeQr('Palatium', 'M'));
    expect(svg.startsWith('<svg')).toBe(true);
    expect(svg).toContain('width="88"');
    expect(svg).toContain('<path d="M');
    expect(svg.match(/<path /g)).toHaveLength(1);
  });
});
