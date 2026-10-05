import { addDays, parseIsoDate, todayInTashkent, UZ_MONTHS, UZ_WEEKDAYS } from '../lib/uzDate';
import { resolvePreset, type DateRange, type FixedPreset } from '../lib/reportPeriods';

const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** "2026-09-19" haqiqiy kalendar sanasimi (2026-02-30 — yo'q). */
export function isIsoDate(value: string | null | undefined): value is string {
  if (!value || !ISO.test(value)) return false;
  const date = parseIsoDate(value);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/** "2026-09-19" → "19-sentabr, 2026". Variantlar: hafta kuni, yilsiz. */
export function formatUzDate(iso: string, options: { weekday?: boolean; year?: boolean } = {}): string {
  if (!isIsoDate(iso)) return iso;
  const { weekday = false, year = true } = options;
  const date = parseIsoDate(iso);
  const day = `${date.getUTCDate()}-${UZ_MONTHS[date.getUTCMonth()]}`;
  const withYear = year ? `${day}, ${date.getUTCFullYear()}` : day;
  if (!weekday) return withYear;
  const weekdayName = UZ_WEEKDAYS[(date.getUTCDay() + 6) % 7];
  return `${weekdayName}, ${withYear}`;
}

/** Oraliq: "1–19-sentabr, 2026" yoki "28-avgust – 3-sentabr, 2026". */
export function formatUzRange(from: string, to: string): string {
  if (from === to) return formatUzDate(from);
  if (!isIsoDate(from) || !isIsoDate(to)) return `${from} – ${to}`;
  const a = parseIsoDate(from);
  const b = parseIsoDate(to);
  if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
    return `${a.getUTCDate()}–${formatUzDate(to)}`;
  }
  if (a.getUTCFullYear() === b.getUTCFullYear()) return `${formatUzDate(from, { year: false })} – ${formatUzDate(to)}`;
  return `${formatUzDate(from)} – ${formatUzDate(to)}`;
}

/** Nisbiy nom: "Bugun", "Kecha" yoki null. */
export function relativeDayLabel(iso: string, today: string = todayInTashkent()): string | null {
  if (iso === today) return 'Bugun';
  if (iso === addDays(today, -1)) return 'Kecha';
  return null;
}

/** Sanani [min, max] oralig'iga qisish (satr taqqoslash ISO uchun to'g'ri). */
export function clampIsoDate(iso: string, min?: string, max?: string): string {
  if (max && iso > max) return max;
  if (min && iso < min) return min;
  return iso;
}

export type RangePreset = FixedPreset | 'custom';

export interface DateRangeValue extends DateRange {
  preset: RangePreset;
}

export const RANGE_PRESET_LABELS: Record<FixedPreset, string> = {
  today: 'Bugun',
  yesterday: 'Kecha',
  week: 'Hafta',
  last7: '7 kun',
  month: 'Oy',
  lastMonth: "O'tgan oy",
  last30: '30 kun',
};

/** Tayyor davrdan oraliq (hafta dushanbadan, oy 1-sanadan). */
export function rangeForPreset(preset: FixedPreset, today: string = todayInTashkent()): DateRangeValue {
  return { preset, ...resolvePreset(preset, today) };
}

/** Oraliq qaysi tayyor davrga mos kelishini topish (bo'lmasa 'custom'). */
export function detectPreset(range: DateRange, presets: readonly FixedPreset[], today: string = todayInTashkent()): RangePreset {
  for (const preset of presets) {
    const r = resolvePreset(preset, today);
    if (r.from === range.from && r.to === range.to) return preset;
  }
  return 'custom';
}
