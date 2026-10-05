/** Formatlangan son matnini ("1 234", "87,5", "12") bo'laklarga ajratadi:
 *  count-up animatsiyasi raqamni o'zgartirib, qolgan belgilarni saqlaydi.
 *  Son bo'lmasa (masalan "—", "08:12") — null. */
export interface ParsedNumber {
  value: number;
  decimals: number;
  prefix: string;
  suffix: string;
  /** Minglik ajratgich bormi (formatNumber — bo'shliq). */
  grouped: boolean;
}

const NUMBER_RE = /^([^\d-]*?)(-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+|-?\d+)(?:[.,](\d+))?([^\d]*)$/;

export function parseDisplayNumber(text: string): ParsedNumber | null {
  const match = text.trim().match(NUMBER_RE);
  if (!match) return null;
  const [, prefix, intPart, fraction = '', suffix] = match;
  // "08:12" kabi vaqt — son emas.
  if (/[:/]/.test(suffix) || /[:/]/.test(prefix)) return null;
  const grouped = /[\s\u00a0\u202f]/.test(intPart);
  const value = Number(`${intPart.replace(/[\s\u00a0\u202f]/g, '')}.${fraction || '0'}`);
  if (!Number.isFinite(value)) return null;
  return { value, decimals: fraction.length, prefix, suffix, grouped };
}

/** `parseDisplayNumber` teskarisi — oraliq qiymatni asl ko'rinishda chiqaradi. */
export function formatLike(value: number, parsed: ParsedNumber): string {
  const fixed = value.toFixed(parsed.decimals);
  const [int, frac] = fixed.split('.');
  const intText = parsed.grouped || Math.abs(parsed.value) >= 10_000 ? int.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') : int;
  return `${parsed.prefix}${intText}${frac ? `,${frac}` : ''}${parsed.suffix}`;
}

/** ease-out cubic. */
export function easeOut(t: number): number {
  const c = Math.min(1, Math.max(0, t));
  return 1 - (1 - c) ** 3;
}
