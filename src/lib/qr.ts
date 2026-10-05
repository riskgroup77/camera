/**
 * Kichik QR-kod koder (ISO/IEC 18004) — tashqi kutubxonasiz.
 *
 * Qamrov: bayt rejimi (UTF-8), xatoni tuzatish darajasi M, 1–10 versiyalar
 * (M da 213 baytgacha — URL uchun yetarli). Maska avtomatik (jarima
 * qoidalari bo'yicha eng yaxshisi) yoki qo'lda tanlanadi.
 *
 * Natija — `boolean[][]` matritsa (`true` = qora modul), `[y][x]` tartibda.
 */

export type QrMatrix = boolean[][];

export interface QrOptions {
  /** 0–7; berilmasa eng past jarimali maska tanlanadi. */
  mask?: number;
  /** Eng kichik versiya (1–10). */
  minVersion?: number;
}

export interface QrCode {
  version: number;
  mask: number;
  size: number;
  modules: QrMatrix;
}

const MAX_VERSION = 10;

// M darajasi: [blokdagi ECC kodso'zlari, [bloklar soni, blokdagi ma'lumot kodso'zlari][]]
const EC_M: Record<number, [number, Array<[number, number]>]> = {
  1: [10, [[1, 16]]],
  2: [16, [[1, 28]]],
  3: [26, [[1, 44]]],
  4: [18, [[2, 32]]],
  5: [24, [[2, 43]]],
  6: [16, [[4, 27]]],
  7: [18, [[4, 31]]],
  8: [22, [[2, 38], [2, 39]]],
  9: [22, [[3, 36], [2, 37]]],
  10: [26, [[4, 43], [1, 44]]],
};

const ALIGN: Record<number, number[]> = {
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

/** Versiya sig'imi (ma'lumot kodso'zlari soni). */
export function dataCapacity(version: number): number {
  return EC_M[version][1].reduce((sum, [count, len]) => sum + count * len, 0);
}

/** Bayt rejimida sig'adigan eng ko'p bayt. */
export function byteCapacity(version: number): number {
  const countBits = version < 10 ? 8 : 16;
  return Math.floor((dataCapacity(version) * 8 - 4 - countBits) / 8);
}

// ───────────────────────────── GF(256) va Reed–Solomon

function gfMul(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      result[j] = gfMul(result[j], root);
      if (j + 1 < degree) result[j] ^= result[j + 1];
    }
    root = gfMul(root, 0x02);
  }
  return result;
}

/** Reed–Solomon qoldig'i (ECC kodso'zlari). */
export function rsRemainder(data: number[], degree: number): number[] {
  const divisor = rsDivisor(degree);
  const result = new Array<number>(degree).fill(0);
  for (const b of data) {
    const factor = b ^ (result.shift() as number);
    result.push(0);
    for (let i = 0; i < degree; i++) result[i] ^= gfMul(divisor[i], factor);
  }
  return result;
}

// ───────────────────────────── Ma'lumotni kodlash

function utf8(text: string): number[] {
  return Array.from(new TextEncoder().encode(text));
}

function chooseVersion(length: number, min: number): number {
  for (let v = Math.max(1, min); v <= MAX_VERSION; v++) if (length <= byteCapacity(v)) return v;
  throw new RangeError(`Matn QR uchun juda uzun (${length} bayt, maks. ${byteCapacity(MAX_VERSION)})`);
}

function dataCodewords(bytes: number[], version: number): number[] {
  const bits: number[] = [];
  const push = (value: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  push(0b0100, 4);
  push(bytes.length, version < 10 ? 8 : 16);
  for (const b of bytes) push(b, 8);
  const capacityBits = dataCapacity(version) * 8;
  push(0, Math.min(4, capacityBits - bits.length));
  push(0, (8 - (bits.length % 8)) % 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let pad = 0xec; out.length < dataCapacity(version); pad ^= 0xec ^ 0x11) out.push(pad);
  return out;
}

function interleave(data: number[], version: number): number[] {
  const [ecLen, groups] = EC_M[version];
  const blocks: number[][] = [];
  let k = 0;
  for (const [count, len] of groups) {
    for (let i = 0; i < count; i++) {
      blocks.push(data.slice(k, k + len));
      k += len;
    }
  }
  const eccs = blocks.map((b) => rsRemainder(b, ecLen));
  const out: number[] = [];
  const maxLen = Math.max(...blocks.map((b) => b.length));
  for (let i = 0; i < maxLen; i++) for (const b of blocks) if (i < b.length) out.push(b[i]);
  for (let i = 0; i < ecLen; i++) for (const e of eccs) out.push(e[i]);
  return out;
}

// ───────────────────────────── Matritsa

class Grid {
  readonly size: number;
  readonly modules: boolean[][];
  readonly reserved: boolean[][];
  readonly version: number;
  constructor(version: number) {
    this.version = version;
    this.size = version * 4 + 17;
    this.modules = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
    this.reserved = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
  }
  fn(x: number, y: number, dark: boolean) {
    this.modules[y][x] = dark;
    this.reserved[y][x] = true;
  }
}

function drawFunctionPatterns(g: Grid) {
  const { size, version } = g;
  for (let i = 0; i < size; i++) {
    g.fn(6, i, i % 2 === 0);
    g.fn(i, 6, i % 2 === 0);
  }
  const finder = (cx: number, cy: number) => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx;
        const y = cy + dy;
        if (x < 0 || y < 0 || x >= size || y >= size) continue;
        const d = Math.max(Math.abs(dx), Math.abs(dy));
        g.fn(x, y, d !== 2 && d !== 4);
      }
    }
  };
  finder(3, 3);
  finder(size - 4, 3);
  finder(3, size - 4);
  const align = ALIGN[version];
  const n = align.length;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0)) continue;
      for (let dy = -2; dy <= 2; dy++)
        for (let dx = -2; dx <= 2; dx++) g.fn(align[i] + dx, align[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }
  drawFormat(g, 0); // joyni band qilish; keyin haqiqiysi yoziladi
  if (version >= 7) {
    let rem = version;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (version << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) === 1;
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      g.fn(a, b, dark);
      g.fn(b, a, dark);
    }
  }
}

/** Format axboroti: M (00) + maska, BCH(15,5), 0x5412 bilan XOR. */
export function formatBits(mask: number): number {
  const data = (0b00 << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

function drawFormat(g: Grid, mask: number) {
  const bits = formatBits(mask);
  const bit = (i: number) => ((bits >>> i) & 1) === 1;
  const { size } = g;
  for (let i = 0; i <= 5; i++) g.fn(8, i, bit(i));
  g.fn(8, 7, bit(6));
  g.fn(8, 8, bit(7));
  g.fn(7, 8, bit(8));
  for (let i = 9; i < 15; i++) g.fn(14 - i, 8, bit(i));
  for (let i = 0; i < 8; i++) g.fn(size - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) g.fn(8, size - 15 + i, bit(i));
  g.fn(8, size - 8, true); // doimiy qora modul
}

function drawCodewords(g: Grid, codewords: number[]) {
  const { size } = g;
  let i = 0;
  const total = codewords.length * 8;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        if (g.reserved[y][x]) continue;
        if (i < total) g.modules[y][x] = ((codewords[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
        i++; // qolgan (remainder) bitlar — oq
      }
    }
  }
}

const MASKS: Array<(x: number, y: number) => boolean> = [
  (x, y) => (x + y) % 2 === 0,
  (_x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

function applyMask(g: Grid, mask: number) {
  const f = MASKS[mask];
  for (let y = 0; y < g.size; y++) for (let x = 0; x < g.size; x++) if (!g.reserved[y][x] && f(x, y)) g.modules[y][x] = !g.modules[y][x];
}

/** Standart jarima (N1–N4) — maska tanlash uchun. */
export function penalty(m: QrMatrix): number {
  const size = m.length;
  let score = 0;
  const lines: boolean[][] = [];
  for (let y = 0; y < size; y++) lines.push(m[y]);
  for (let x = 0; x < size; x++) lines.push(m.map((row) => row[x]));
  const PAT_A = [true, false, true, true, true, false, true, false, false, false, false];
  const PAT_B = [false, false, false, false, true, false, true, true, true, false, true];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= size; i++) {
      if (i < size && line[i] === line[i - 1]) run++;
      else {
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
    }
    for (let i = 0; i + 11 <= size; i++) {
      let a = true;
      let b = true;
      for (let k = 0; k < 11; k++) {
        if (line[i + k] !== PAT_A[k]) a = false;
        if (line[i + k] !== PAT_B[k]) b = false;
      }
      if (a) score += 40;
      if (b) score += 40;
    }
  }
  for (let y = 0; y + 1 < size; y++)
    for (let x = 0; x + 1 < size; x++) {
      const c = m[y][x];
      if (m[y][x + 1] === c && m[y + 1][x] === c && m[y + 1][x + 1] === c) score += 3;
    }
  let dark = 0;
  for (const row of m) for (const v of row) if (v) dark++;
  score += Math.floor(Math.abs((dark * 100) / (size * size) - 50) / 5) * 10;
  return score;
}

/** Matnni QR matritsaga kodlaydi (bayt rejimi, M daraja). */
export function encodeQr(text: string, options: QrOptions = {}): QrCode {
  const bytes = utf8(text);
  const version = chooseVersion(bytes.length, options.minVersion ?? 1);
  const codewords = interleave(dataCodewords(bytes, version), version);
  const build = (mask: number) => {
    const g = new Grid(version);
    drawFunctionPatterns(g);
    drawCodewords(g, codewords);
    applyMask(g, mask);
    drawFormat(g, mask);
    return g;
  };
  if (options.mask !== undefined) {
    if (!Number.isInteger(options.mask) || options.mask < 0 || options.mask > 7) throw new RangeError('Maska 0–7 oralig\'ida bo\'lishi kerak');
    const g = build(options.mask);
    return { version, mask: options.mask, size: g.size, modules: g.modules };
  }
  let best: { mask: number; g: Grid; score: number } | null = null;
  for (let mask = 0; mask < 8; mask++) {
    const g = build(mask);
    const score = penalty(g.modules);
    if (!best || score < best.score) best = { mask, g, score };
  }
  return { version, mask: best!.mask, size: best!.g.size, modules: best!.g.modules };
}

/** SVG `path` (`d`) — har qora modul 1×1 kvadrat; `margin` — sokin hudud. */
export function qrPath(modules: QrMatrix, margin = 4): string {
  const parts: string[] = [];
  modules.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (!row[x]) {
        x++;
        continue;
      }
      const start = x;
      while (x < row.length && row[x]) x++;
      parts.push(`M${start + margin} ${y + margin}h${x - start}v1h-${x - start}z`);
    }
  });
  return parts.join('');
}

/** To'liq SVG matni (chop etish / yuklab olish uchun). */
export function qrSvg(text: string, options: QrOptions & { margin?: number; dark?: string; light?: string } = {}): string {
  const { margin = 4, dark = '#000', light = '#fff' } = options;
  const qr = encodeQr(text, options);
  const dim = qr.size + margin * 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}" shape-rendering="crispEdges"><rect width="${dim}" height="${dim}" fill="${light}"/><path d="${qrPath(qr.modules, margin)}" fill="${dark}"/></svg>`;
}
