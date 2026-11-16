/**
 * Минимальный QR-энкодер (byte mode, версии 1–10, ECC L/M).
 *
 * Нужен ровно один сценарий — QR в поповере «Get App» (Kimi parity: 88×88 px).
 * Внешняя библиотека не подключается: виджет собирается в single-file IIFE
 * (`vite.config.wc.ts`, `codeSplitting: false`), и runtime-зависимость на ~30 KB
 * прошла бы в бандл СЭД (бумага бюджета — 084).
 *
 * Корректность матрицы проверяется юнит-тестом против эталонной реализации
 * (`qrcode`, только devDependency): совпадение размера, версии и каждой моды.
 */

export type QrEcc = 'L' | 'M';

export interface QrCode {
  /** Число модулей по стороне (без quiet zone). */
  readonly size: number;
  readonly version: number;
  readonly mask: number;
  /** `modules[y][x]` — true = тёмный модуль. */
  readonly modules: readonly (readonly boolean[])[];
}

interface BlockGroup {
  /** Количество RS-блоков в группе. */
  readonly count: number;
  /** Число data-codewords в одном блоке группы. */
  readonly data: number;
}

interface VersionSpec {
  /** ECC codewords в одном блоке. */
  readonly ecc: number;
  readonly groups: readonly BlockGroup[];
}

/** Таблица ISO/IEC 18004 для версий 1–10 (меньше — не влезет, больше — не нужно). */
const SPECS: Readonly<Record<number, Readonly<Record<QrEcc, VersionSpec>>>> = {
  1: {
    L: { ecc: 7, groups: [{ count: 1, data: 19 }] },
    M: { ecc: 10, groups: [{ count: 1, data: 16 }] },
  },
  2: {
    L: { ecc: 10, groups: [{ count: 1, data: 34 }] },
    M: { ecc: 16, groups: [{ count: 1, data: 28 }] },
  },
  3: {
    L: { ecc: 15, groups: [{ count: 1, data: 55 }] },
    M: { ecc: 26, groups: [{ count: 1, data: 44 }] },
  },
  4: {
    L: { ecc: 20, groups: [{ count: 1, data: 80 }] },
    M: { ecc: 18, groups: [{ count: 2, data: 32 }] },
  },
  5: {
    L: { ecc: 26, groups: [{ count: 1, data: 108 }] },
    M: { ecc: 24, groups: [{ count: 2, data: 43 }] },
  },
  6: {
    L: { ecc: 18, groups: [{ count: 2, data: 68 }] },
    M: { ecc: 16, groups: [{ count: 4, data: 27 }] },
  },
  7: {
    L: { ecc: 20, groups: [{ count: 2, data: 78 }] },
    M: { ecc: 18, groups: [{ count: 4, data: 31 }] },
  },
  8: {
    L: { ecc: 24, groups: [{ count: 2, data: 97 }] },
    M: {
      ecc: 22,
      groups: [
        { count: 2, data: 38 },
        { count: 2, data: 39 },
      ],
    },
  },
  9: {
    L: { ecc: 30, groups: [{ count: 2, data: 116 }] },
    M: {
      ecc: 22,
      groups: [
        { count: 3, data: 36 },
        { count: 2, data: 37 },
      ],
    },
  },
  10: {
    L: {
      ecc: 18,
      groups: [
        { count: 2, data: 68 },
        { count: 2, data: 69 },
      ],
    },
    M: {
      ecc: 26,
      groups: [
        { count: 4, data: 43 },
        { count: 1, data: 44 },
      ],
    },
  },
};

const MAX_VERSION = 10;

/** Центры alignment-паттернов по версиям (6 всегда первый, последний = size - 7). */
const ALIGNMENT_CENTERS: Readonly<Record<number, readonly number[]>> = {
  1: [],
  2: [6, 18],
  3: [6, 22],
  4: [6, 26],
  5: [6, 30],
  6: [6, 34],
  7: [6, 22, 38],
  8: [6, 24, 42],
  9: [6, 26, 46],
  10: [6, 28, 50],
};

const ECC_BITS: Readonly<Record<QrEcc, number>> = { L: 1, M: 0 };

function utf8Bytes(text: string): number[] {
  return Array.from(new TextEncoder().encode(text));
}

function specOf(version: number, ecc: QrEcc): VersionSpec {
  const spec = SPECS[version]?.[ecc];
  if (!spec) throw new Error(`QR: нет таблицы для версии ${version}/${ecc}`);
  return spec;
}

function dataCodewordCount(spec: VersionSpec): number {
  return spec.groups.reduce((sum, group) => sum + group.count * group.data, 0);
}

function charCountBits(version: number): number {
  return version < 10 ? 8 : 16;
}

function pickVersion(byteLength: number, ecc: QrEcc): number {
  for (let version = 1; version <= MAX_VERSION; version += 1) {
    const capacityBits = dataCodewordCount(specOf(version, ecc)) * 8;
    const neededBits = 4 + charCountBits(version) + byteLength * 8;
    if (neededBits <= capacityBits) return version;
  }
  throw new Error(`QR: ${byteLength} байт не влезает в версию ${MAX_VERSION}`);
}

class BitBuffer {
  readonly bits: number[] = [];

  push(value: number, length: number): void {
    for (let i = length - 1; i >= 0; i -= 1) this.bits.push((value >>> i) & 1);
  }
}

function buildDataCodewords(bytes: readonly number[], version: number, ecc: QrEcc): number[] {
  const spec = specOf(version, ecc);
  const capacityBits = dataCodewordCount(spec) * 8;
  const buffer = new BitBuffer();
  buffer.push(0b0100, 4);
  buffer.push(bytes.length, charCountBits(version));
  for (const byte of bytes) buffer.push(byte, 8);

  buffer.push(0, Math.min(4, capacityBits - buffer.bits.length));
  while (buffer.bits.length % 8 !== 0) buffer.bits.push(0);

  const codewords: number[] = [];
  for (let i = 0; i < buffer.bits.length; i += 8) {
    codewords.push(Number.parseInt(buffer.bits.slice(i, i + 8).join(''), 2));
  }
  // Pad codewords чередуются 0xEC / 0x11 (ISO/IEC 18004 §8.4.9).
  for (let pad = 0; codewords.length < dataCodewordCount(spec); pad += 1) {
    codewords.push(pad % 2 === 0 ? 0xec : 0x11);
  }
  return codewords;
}

// —— Reed–Solomon над GF(256), примитивный полином 0x11D ——

const GF_EXP: number[] = [];
const GF_LOG: number[] = [];
{
  let value = 1;
  for (let i = 0; i < 256; i += 1) {
    GF_EXP[i] = value;
    GF_LOG[value] = i;
    value <<= 1;
    if (value & 0x100) value ^= 0x11d;
  }
}

function gfMultiply(left: number, right: number): number {
  if (left === 0 || right === 0) return 0;
  return GF_EXP[(GF_LOG[left] + GF_LOG[right]) % 255];
}

function generatorPolynomial(degree: number): number[] {
  let poly = [1];
  for (let i = 0; i < degree; i += 1) {
    const next = new Array<number>(poly.length + 1).fill(0);
    for (let j = 0; j < poly.length; j += 1) {
      next[j] ^= poly[j];
      next[j + 1] ^= gfMultiply(poly[j], GF_EXP[i]);
    }
    poly = next;
  }
  return poly;
}

function reedSolomon(data: readonly number[], eccLength: number): number[] {
  const divisor = generatorPolynomial(eccLength);
  const remainder = new Array<number>(eccLength).fill(0);
  for (const byte of data) {
    const factor = byte ^ remainder[0];
    remainder.shift();
    remainder.push(0);
    for (let i = 0; i < eccLength; i += 1) {
      remainder[i] ^= gfMultiply(divisor[i + 1], factor);
    }
  }
  return remainder;
}

function interleaveCodewords(data: readonly number[], version: number, ecc: QrEcc): number[] {
  const spec = specOf(version, ecc);
  const blocks: number[][] = [];
  const eccBlocks: number[][] = [];
  let offset = 0;
  for (const group of spec.groups) {
    for (let block = 0; block < group.count; block += 1) {
      const payload = data.slice(offset, offset + group.data);
      offset += group.data;
      blocks.push(payload);
      eccBlocks.push(reedSolomon(payload, spec.ecc));
    }
  }

  const result: number[] = [];
  const maxData = Math.max(...blocks.map(block => block.length));
  for (let i = 0; i < maxData; i += 1) {
    for (const block of blocks) if (i < block.length) result.push(block[i]);
  }
  for (let i = 0; i < spec.ecc; i += 1) {
    for (const block of eccBlocks) result.push(block[i]);
  }
  return result;
}

// —— Построение матрицы ——

class Matrix {
  readonly size: number;
  readonly modules: boolean[][];
  readonly reserved: boolean[][];

  constructor(version: number) {
    this.size = version * 4 + 17;
    this.modules = Array.from({ length: this.size }, () =>
      new Array<boolean>(this.size).fill(false)
    );
    this.reserved = Array.from({ length: this.size }, () =>
      new Array<boolean>(this.size).fill(false)
    );
  }

  set(x: number, y: number, dark: boolean): void {
    if (x < 0 || y < 0 || x >= this.size || y >= this.size) return;
    this.modules[y][x] = dark;
    this.reserved[y][x] = true;
  }
}

function drawFinder(matrix: Matrix, centerX: number, centerY: number): void {
  for (let dy = -4; dy <= 4; dy += 1) {
    for (let dx = -4; dx <= 4; dx += 1) {
      const distance = Math.max(Math.abs(dx), Math.abs(dy));
      matrix.set(centerX + dx, centerY + dy, distance !== 2 && distance !== 4);
    }
  }
}

function drawAlignment(matrix: Matrix, centerX: number, centerY: number): void {
  for (let dy = -2; dy <= 2; dy += 1) {
    for (let dx = -2; dx <= 2; dx += 1) {
      matrix.set(centerX + dx, centerY + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }
}

function drawFunctionPatterns(matrix: Matrix, version: number, ecc: QrEcc): void {
  const { size } = matrix;
  for (let i = 0; i < size; i += 1) {
    matrix.set(6, i, i % 2 === 0);
    matrix.set(i, 6, i % 2 === 0);
  }
  drawFinder(matrix, 3, 3);
  drawFinder(matrix, size - 4, 3);
  drawFinder(matrix, 3, size - 4);

  const centers = ALIGNMENT_CENTERS[version];
  for (let i = 0; i < centers.length; i += 1) {
    for (let j = 0; j < centers.length; j += 1) {
      const corner =
        (i === 0 && j === 0) ||
        (i === 0 && j === centers.length - 1) ||
        (i === centers.length - 1 && j === 0);
      if (!corner) drawAlignment(matrix, centers[i], centers[j]);
    }
  }

  drawFormatBits(matrix, ecc, 0);
  if (version >= 7) drawVersionBits(matrix, version);
}

function drawFormatBits(matrix: Matrix, ecc: QrEcc, mask: number): void {
  const data = (ECC_BITS[ecc] << 3) | mask;
  let remainder = data;
  for (let i = 0; i < 10; i += 1) remainder = (remainder << 1) ^ ((remainder >>> 9) * 0x537);
  const bits = ((data << 10) | remainder) ^ 0x5412;
  const { size } = matrix;

  for (let i = 0; i <= 5; i += 1) matrix.set(8, i, ((bits >>> i) & 1) === 1);
  matrix.set(8, 7, ((bits >>> 6) & 1) === 1);
  matrix.set(8, 8, ((bits >>> 7) & 1) === 1);
  matrix.set(7, 8, ((bits >>> 8) & 1) === 1);
  for (let i = 9; i < 15; i += 1) matrix.set(14 - i, 8, ((bits >>> i) & 1) === 1);

  for (let i = 0; i < 8; i += 1) matrix.set(size - 1 - i, 8, ((bits >>> i) & 1) === 1);
  for (let i = 8; i < 15; i += 1) matrix.set(8, size - 15 + i, ((bits >>> i) & 1) === 1);
  matrix.set(8, size - 8, true);
}

function drawVersionBits(matrix: Matrix, version: number): void {
  let remainder = version;
  for (let i = 0; i < 12; i += 1) remainder = (remainder << 1) ^ ((remainder >>> 11) * 0x1f25);
  const bits = (version << 12) | remainder;
  const { size } = matrix;
  for (let i = 0; i < 18; i += 1) {
    const dark = ((bits >>> i) & 1) === 1;
    const a = size - 11 + (i % 3);
    const b = Math.floor(i / 3);
    matrix.set(a, b, dark);
    matrix.set(b, a, dark);
  }
}

function maskBit(mask: number, x: number, y: number): boolean {
  switch (mask) {
    case 0:
      return (x + y) % 2 === 0;
    case 1:
      return y % 2 === 0;
    case 2:
      return x % 3 === 0;
    case 3:
      return (x + y) % 3 === 0;
    case 4:
      return (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0;
    case 5:
      return ((x * y) % 2) + ((x * y) % 3) === 0;
    case 6:
      return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0;
    default:
      return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
  }
}

function placeData(matrix: Matrix, codewords: readonly number[]): void {
  const { size } = matrix;
  let bitIndex = 0;
  const totalBits = codewords.length * 8;
  const nextBit = (): boolean => {
    if (bitIndex >= totalBits) return false;
    const value = ((codewords[bitIndex >>> 3] >>> (7 - (bitIndex & 7))) & 1) === 1;
    bitIndex += 1;
    return value;
  };

  let upward = true;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let step = 0; step < size; step += 1) {
      const y = upward ? size - 1 - step : step;
      for (let column = 0; column < 2; column += 1) {
        const x = right - column;
        if (matrix.reserved[y][x]) continue;
        matrix.modules[y][x] = nextBit();
      }
    }
    upward = !upward;
  }
}

function applyMask(matrix: Matrix, mask: number): void {
  for (let y = 0; y < matrix.size; y += 1) {
    for (let x = 0; x < matrix.size; x += 1) {
      if (!matrix.reserved[y][x] && maskBit(mask, x, y))
        matrix.modules[y][x] = !matrix.modules[y][x];
    }
  }
}

function penaltyScore(modules: readonly (readonly boolean[])[]): number {
  const size = modules.length;
  let score = 0;

  // N1: серии одинаковых модулей длиной ≥ 5.
  const runScore = (get: (i: number) => boolean): void => {
    let run = 1;
    for (let i = 1; i < size; i += 1) {
      if (get(i) === get(i - 1)) {
        run += 1;
      } else {
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
    }
    if (run >= 5) score += 3 + (run - 5);
  };
  for (let y = 0; y < size; y += 1) runScore(x => modules[y][x]);
  for (let x = 0; x < size; x += 1) runScore(y => modules[y][x]);

  // N2: блоки 2×2 одного цвета.
  for (let y = 0; y < size - 1; y += 1) {
    for (let x = 0; x < size - 1; x += 1) {
      const color = modules[y][x];
      if (
        modules[y][x + 1] === color &&
        modules[y + 1][x] === color &&
        modules[y + 1][x + 1] === color
      ) {
        score += 3;
      }
    }
  }

  // N3: паттерн 1:1:3:1:1 с тихими модулями 0000 или 0000 по краю.
  const pattern = [true, false, true, true, true, false, true];
  const matches = (get: (i: number) => boolean, start: number): boolean => {
    for (let i = 0; i < 7; i += 1) if (get(start + i) !== pattern[i]) return false;
    const quietBefore = [1, 2, 3, 4].every(offset => start - offset < 0 || !get(start - offset));
    const quietAfter = [1, 2, 3, 4].every(
      offset => start + 6 + offset >= size || !get(start + 6 + offset)
    );
    return quietBefore || quietAfter;
  };
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x <= size - 7; x += 1) if (matches(i => modules[y][i], x)) score += 40;
  }
  for (let x = 0; x < size; x += 1) {
    for (let y = 0; y <= size - 7; y += 1) if (matches(i => modules[i][x], y)) score += 40;
  }

  // N4: дисбаланс тёмных модулей.
  let dark = 0;
  for (const row of modules) for (const module of row) if (module) dark += 1;
  const percent = (dark * 100) / (size * size);
  score += Math.floor(Math.abs(percent - 50) / 5) * 10;
  return score;
}

function buildMatrix(
  version: number,
  ecc: QrEcc,
  codewords: readonly number[],
  mask: number
): Matrix {
  const matrix = new Matrix(version);
  drawFunctionPatterns(matrix, version, ecc);
  placeData(matrix, codewords);
  applyMask(matrix, mask);
  drawFormatBits(matrix, ecc, mask);
  return matrix;
}

/**
 * Собирает QR-код для строки (UTF-8, byte mode).
 *
 * `maskOverride` нужен тесту: маска сравнивается с эталонной реализацией
 * поштучно, иначе расхождение эвристики штрафа маскировало бы ошибки модулей.
 */
export function encodeQr(text: string, ecc: QrEcc = 'M', maskOverride?: number): QrCode {
  const bytes = utf8Bytes(text);
  const version = pickVersion(bytes.length, ecc);
  const codewords = interleaveCodewords(buildDataCodewords(bytes, version, ecc), version, ecc);

  let best: { mask: number; modules: boolean[][]; penalty: number } | null = null;
  const masks =
    maskOverride === undefined ? [0, 1, 2, 3, 4, 5, 6, 7] : [((maskOverride % 8) + 8) % 8];
  for (const mask of masks) {
    const matrix = buildMatrix(version, ecc, codewords, mask);
    const penalty = penaltyScore(matrix.modules);
    if (!best || penalty < best.penalty) best = { mask, modules: matrix.modules, penalty };
  }

  return { size: version * 4 + 17, version, mask: best!.mask, modules: best!.modules };
}

export interface QrSvgOptions {
  /** Сторона SVG в px (по умолчанию 88). */
  readonly size?: number;
  /** Цвет модулей; по умолчанию `currentColor` — палитра приходит из CSS-токенов. */
  readonly dark?: string;
  /** Фон; по умолчанию прозрачный — белая подложка даётся обёрткой. */
  readonly light?: string;
  /** Field name: quiet zone в модулях (по умолчанию 0 — паддинг даёт обёртка). */
  readonly margin?: number;
}

/**
 * Рендерит QR в SVG-строку. Один `<path>` вместо тысяч `<rect>` — дешевле и по
 * разметке, и по рендеру в поповере.
 */
export function qrToSvg(code: QrCode, options: QrSvgOptions = {}): string {
  const { size = 88, dark = 'currentColor', light = 'transparent', margin = 0 } = options;
  const dimension = code.size + margin * 2;
  const parts: string[] = [];
  for (let y = 0; y < code.size; y += 1) {
    for (let x = 0; x < code.size; x += 1) {
      if (code.modules[y][x]) parts.push(`M${x + margin} ${y + margin}h1v1h-1z`);
    }
  }
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${dimension} ${dimension}" shape-rendering="crispEdges" role="img" aria-hidden="true">`,
    light === 'transparent'
      ? ''
      : `<rect width="${dimension}" height="${dimension}" fill="${light}"/>`,
    `<path d="${parts.join('')}" fill="${dark}"/>`,
    '</svg>',
  ].join('');
}
