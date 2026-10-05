/** "Aliyev Vali Karimovich" → "AV". Bo'sh bo'lsa "?". */
export function initials(name: string | null | undefined): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  const letters = words.slice(0, 2).map((word) => Array.from(word)[0] ?? '');
  return letters.join('').toUpperCase();
}

/** Raqamni o'zbekcha ko'rinishda: 12 345. `null` → "—". */
export function formatNumber(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('ru-RU', { maximumFractionDigits: fractionDigits, minimumFractionDigits: 0 });
}

/** Foiz: 87.456 → "87,5%". `null` → "—". */
export function formatPercent(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${formatNumber(value, fractionDigits)}%`;
}
