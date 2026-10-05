/** Semantik ohanglar — barcha komponentlarda bir xil ma'no:
 *  success = keldi / yaxshi, warning = kech / diqqat, danger = kelmadi / xavf,
 *  neutral = ma'lumot yo'q / hali kelmagan. */
export type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

/** Yumshoq fon + rangli matn (badge, ikonka chipi). */
export const TONE_SOFT: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  primary: 'bg-primary-soft text-primary',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  info: 'bg-info-soft text-info',
};

/** To'liq rangli fon (nuqta, chiziq, progress). */
export const TONE_SOLID: Record<Tone, string> = {
  neutral: 'bg-subtle',
  primary: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
};

export const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-muted',
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

/** SVG uchun: `stroke="currentColor"` bilan ishlatiladi. */
export const TONE_STROKE = TONE_TEXT;

export const TONE_RING: Record<Tone, string> = {
  neutral: 'ring-border-strong',
  primary: 'ring-primary',
  success: 'ring-success',
  warning: 'ring-warning',
  danger: 'ring-danger',
  info: 'ring-info',
};

export const TONE_BORDER: Record<Tone, string> = {
  neutral: 'border-border-strong',
  primary: 'border-primary',
  success: 'border-success',
  warning: 'border-warning',
  danger: 'border-danger',
  info: 'border-info',
};

export interface RateThresholds {
  /** Shundan yuqori — yaxshi (success). */
  good: number;
  /** Shundan yuqori — o'rtacha (warning); pastda — danger. */
  warn: number;
}

/** Davomat/punktuallik foizlari uchun yagona chegaralar. */
export const DEFAULT_RATE_THRESHOLDS: RateThresholds = { good: 85, warn: 70 };

/** Foiz (0–100) → ohang. `null` — ma'lumot yo'q (neutral). */
export function toneForRate(
  rate: number | null | undefined,
  thresholds: RateThresholds = DEFAULT_RATE_THRESHOLDS,
): Tone {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return 'neutral';
  if (rate >= thresholds.good) return 'success';
  if (rate >= thresholds.warn) return 'warning';
  return 'danger';
}
