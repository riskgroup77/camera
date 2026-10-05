import type { EventDetails } from '../types';

/** Detektor o'lchagan qiymatlar — operatorga tushunarli nomlar bilan
 *  (kalitlar app/jobs/*.py dagi raise_event(details=...) bilan bir xil). */
const METRIC_LABELS: Record<string, string> = {
  fire_fraction: 'Olov rangidagi ulush',
  motion: 'Harakat',
  baseline: 'Odatdagi harakat',
  threshold: 'Chegara',
  people: 'Odamlar soni',
  distance_a: "Qo'l–og'iz masofasi (1-kadr)",
  distance_b: "Qo'l–og'iz masofasi (2-kadr)",
  mask_a: 'Niqob belgisi (1-kadr)',
  mask_b: 'Niqob belgisi (2-kadr)',
  white_a: 'Oq rang ulushi (1-kadr)',
  white_b: 'Oq rang ulushi (2-kadr)',
  unmatched: 'Tanilmagan yuzlar',
  closest: "Eng yaqin o'xshashlik",
  closed: "Ko'z yumuq kadrlar",
  frames: 'Kadrlar',
  ratio: 'Ulush',
};

const PERCENT_KEYS = new Set(['fire_fraction', 'ratio']);

export interface MetricRow {
  key: string;
  label: string;
  value: string;
}

export function formatMetric(key: string, value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value !== 'number') return String(value);
  if (PERCENT_KEYS.has(key)) return `${(value * 100).toFixed(1).replace('.', ',')}%`;
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace('.', ',');
}

/** Bo'sh qiymatlarsiz, tartibi saqlangan o'lchovlar ro'yxati. */
export function detailMetrics(details: EventDetails | null | undefined): MetricRow[] {
  return Object.entries(details?.metrics ?? {})
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => ({ key, label: METRIC_LABELS[key] ?? key, value: formatMetric(key, value) }));
}
