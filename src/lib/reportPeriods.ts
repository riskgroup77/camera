import { addDays, daysBetweenInclusive, parseIsoDate, todayInTashkent, toIsoDate } from './uzDate';

export type PeriodPreset = 'today' | 'yesterday' | 'week' | 'last7' | 'month' | 'lastMonth' | 'last30' | 'custom';
export type FixedPreset = Exclude<PeriodPreset, 'custom'>;

export interface DateRange {
  from: string;
  to: string;
}

/** Backend bilan bir xil: app/services/analytics.py MAX_RANGE_DAYS. */
export const MAX_RANGE_DAYS = 92;

export const PERIOD_PRESETS: { value: FixedPreset; label: string }[] = [
  { value: 'today', label: 'Bugun' },
  { value: 'yesterday', label: 'Kecha' },
  { value: 'week', label: 'Shu hafta' },
  { value: 'last7', label: '7 kun' },
  { value: 'month', label: 'Shu oy' },
  { value: 'lastMonth', label: "O'tgan oy" },
  { value: 'last30', label: '30 kun' },
];

export function isFixedPreset(value: string | null): value is FixedPreset {
  return PERIOD_PRESETS.some((preset) => preset.value === value);
}

export function resolvePreset(preset: FixedPreset, today: string = todayInTashkent()): DateRange {
  switch (preset) {
    case 'today':
      return { from: today, to: today };
    case 'yesterday': {
      const day = addDays(today, -1);
      return { from: day, to: day };
    }
    case 'week': {
      // Hafta dushanbadan boshlanadi.
      const mondayOffset = (parseIsoDate(today).getUTCDay() + 6) % 7;
      return { from: addDays(today, -mondayOffset), to: today };
    }
    case 'last7':
      return { from: addDays(today, -6), to: today };
    case 'month':
      return { from: `${today.slice(0, 8)}01`, to: today };
    case 'lastMonth': {
      const lastDay = parseIsoDate(`${today.slice(0, 8)}01`);
      lastDay.setUTCDate(0);
      const firstDay = new Date(Date.UTC(lastDay.getUTCFullYear(), lastDay.getUTCMonth(), 1));
      return { from: toIsoDate(firstDay), to: toIsoDate(lastDay) };
    }
    case 'last30':
      return { from: addDays(today, -29), to: today };
  }
}

export function validateRange(from: string, to: string): string | null {
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  if (!iso.test(from) || !iso.test(to)) return 'Ikkala sanani ham tanlang';
  if (from > to) return "Boshlanish sanasi tugash sanasidan keyin bo'lishi mumkin emas";
  if (daysBetweenInclusive(from, to) > MAX_RANGE_DAYS) return `Oraliq ${MAX_RANGE_DAYS} kundan oshmasligi kerak`;
  return null;
}
